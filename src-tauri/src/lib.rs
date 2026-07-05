use std::net::TcpListener;
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{Emitter, Manager};
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

pub struct SidecarState {
    pub url: String,
    pub token: String,
    pub child: Mutex<Option<CommandChild>>,
    /// Current sidecar PID — atomic because the watchdog replaces it on restart.
    pub pid: AtomicU32,
    /// Set on window close so the watchdog doesn't "rescue" a sidecar we
    /// killed on purpose during shutdown.
    pub shutting_down: AtomicBool,
}

/// Everything needed to (re)spawn the sidecar with identical parameters.
#[derive(Clone)]
struct SidecarLaunch {
    port: u16,
    data_dir: String,
    app_version: String,
    token: String,
}

/// Generate the IPC auth token: 256 bits from the OS CSPRNG, hex-encoded.
/// This token is the only auth on an API that can export biometric centroids,
/// so guessable entropy sources (time/PID — the previous scheme) are not
/// acceptable (#112).
fn generate_token() -> String {
    use rand::RngCore;
    let mut bytes = [0u8; 32];
    rand::rngs::OsRng.fill_bytes(&mut bytes);
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Kill the sidecar process tree on Windows so PyInstaller's bootstrap and
/// its Python worker subprocess are both terminated (child.kill() only kills
/// the bootstrap, leaving the worker as an orphan that holds the port).
#[cfg(target_os = "windows")]
fn kill_sidecar_tree(pid: u32) {
    let _ = std::process::Command::new("taskkill")
        .args(["/F", "/T", "/PID", &pid.to_string()])
        .output();
}

#[cfg(not(target_os = "windows"))]
fn kill_sidecar_tree(pid: u32) {
    let _ = std::process::Command::new("kill")
        .args(["-9", &pid.to_string()])
        .output();
}

/// Best-effort cleanup of orphaned sidecar processes left by a previous run that
/// crashed or was force-closed without our window-close handler running. Such an
/// orphan holds the SQLite WAL and would shadow the fresh sidecar. Called once at
/// startup before spawning our own; faces-h is effectively single-instance, so
/// there is no legitimately-running sidecar to preserve at this point.
#[cfg(target_os = "windows")]
fn kill_orphaned_sidecars() {
    let _ = std::process::Command::new("taskkill")
        .args(["/F", "/T", "/IM", "faces-sidecar.exe"])
        .output();
}

#[cfg(not(target_os = "windows"))]
fn kill_orphaned_sidecars() {
    let _ = std::process::Command::new("pkill")
        .args(["-9", "-f", "faces-sidecar"])
        .output();
}

/// Bind a TCP listener on port 0 to let the OS pick a free port, read it, then
/// drop the listener so the port is available for the sidecar.
pub fn allocate_port() -> u16 {
    let listener = TcpListener::bind("127.0.0.1:0").expect("failed to bind ephemeral port");
    listener.local_addr().expect("no local addr").port()
    // listener is dropped here, freeing the port before the caller can use it
}

/// Poll until the TCP port accepts connections or the timeout elapses.
/// Logs a progress line every 10 s so the app.log shows the wait is alive.
fn wait_for_port(port: u16, timeout: Duration) -> bool {
    use std::net::TcpStream;
    let start = Instant::now();
    let deadline = start + timeout;
    let mut next_log = start + Duration::from_secs(10);
    while Instant::now() < deadline {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return true;
        }
        let now = Instant::now();
        if now >= next_log {
            log::info!(
                "waiting for sidecar on port {port} — {} s elapsed",
                now.duration_since(start).as_secs()
            );
            next_log += Duration::from_secs(10);
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    false
}

/// One quick liveness probe: is the sidecar still accepting TCP connections?
fn sidecar_healthy(port: u16) -> bool {
    use std::net::{SocketAddr, TcpStream};
    let addr: SocketAddr = ([127, 0, 0, 1], port).into();
    TcpStream::connect_timeout(&addr, Duration::from_secs(2)).is_ok()
}

/// Spawn the sidecar process. Used for the initial launch and by the watchdog
/// when it restarts a dead sidecar with identical parameters (#119).
fn spawn_sidecar(
    app: &tauri::AppHandle,
    launch: &SidecarLaunch,
) -> Result<CommandChild, String> {
    let (_, child) = app
        .shell()
        .sidecar("faces-sidecar")
        .map_err(|e| e.to_string())?
        .args([
            "--port", &launch.port.to_string(),
            "--data-dir", &launch.data_dir,
            "--app-version", &launch.app_version,
            "--token", &launch.token,
            "--parent-pid", &std::process::id().to_string(),
        ])
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(child)
}

/// How many consecutive failed 5-second liveness probes before the watchdog
/// declares the sidecar dead and attempts a restart.
const WATCHDOG_FAILURE_LIMIT: u32 = 3;
const WATCHDOG_INTERVAL: Duration = Duration::from_secs(5);

/// Supervise the sidecar after it is ready: probe liveness, restart it once if
/// it dies mid-session, and surface a fatal error if the restart fails too.
/// Keeps app + sidecar acting as one application (#119).
fn watchdog_loop(handle: tauri::AppHandle, launch: SidecarLaunch, url: String) {
    let mut consecutive_failures: u32 = 0;
    let mut restart_attempted = false;

    loop {
        std::thread::sleep(WATCHDOG_INTERVAL);
        let state = handle.state::<SidecarState>();
        if state.shutting_down.load(Ordering::SeqCst) {
            return;
        }
        if sidecar_healthy(launch.port) {
            consecutive_failures = 0;
            continue;
        }
        consecutive_failures += 1;
        if consecutive_failures < WATCHDOG_FAILURE_LIMIT {
            continue;
        }
        if state.shutting_down.load(Ordering::SeqCst) {
            return;
        }
        if restart_attempted {
            log::error!("sidecar died again after a restart — giving up");
            let _ = handle.emit("sidecar-error", "Engine stopped and could not be restarted");
            return;
        }
        restart_attempted = true;
        log::warn!(
            "sidecar unresponsive for {} s — restarting it",
            consecutive_failures as u64 * WATCHDOG_INTERVAL.as_secs()
        );
        kill_sidecar_tree(state.pid.load(Ordering::SeqCst));

        match spawn_sidecar(&handle, &launch) {
            Ok(child) => {
                let new_pid = child.pid();
                state.pid.store(new_pid, Ordering::SeqCst);
                if let Ok(mut guard) = state.child.lock() {
                    *guard = Some(child);
                }
                if wait_for_port(launch.port, Duration::from_secs(180)) {
                    log::info!("sidecar restarted — pid={new_pid}");
                    let payload =
                        serde_json::json!({ "url": url, "token": launch.token, "restarted": true });
                    let _ = handle.emit("sidecar-ready", payload);
                    consecutive_failures = 0;
                } else {
                    log::error!("restarted sidecar never bound port {}", launch.port);
                    let _ = handle.emit("sidecar-error", "Engine failed to restart");
                    return;
                }
            }
            Err(e) => {
                log::error!("sidecar respawn failed: {e}");
                let _ = handle.emit("sidecar-error", "Engine failed to restart");
                return;
            }
        }
    }
}

/// Return the sidecar base URL that the frontend should use for HTTP/WS.
#[tauri::command]
fn get_sidecar_url(state: tauri::State<SidecarState>) -> String {
    state.url.clone()
}

/// Return the IPC auth token so the frontend can attach it to API requests.
#[tauri::command]
fn get_sidecar_token(state: tauri::State<SidecarState>) -> String {
    state.token.clone()
}

/// Open a file path in the default viewer via ShellExecute (opener crate).
/// The path must exist on disk, and the path is never re-parsed by cmd.exe —
/// the previous `cmd /c start` route let metacharacters in a crafted filename
/// (e.g. `x & evil.exe.jpg`) break out of the argument (#112).
#[tauri::command]
fn open_in_viewer(path: String) -> Result<(), String> {
    if !std::path::Path::new(&path).exists() {
        return Err(format!("File not found: {path}"));
    }
    opener::open(&path).map_err(|e| e.to_string())
}

/// Open the system file manager with the given file selected.
#[tauri::command]
fn reveal_in_explorer(path: String) -> Result<(), String> {
    if !std::path::Path::new(&path).exists() {
        return Err(format!("File not found: {path}"));
    }
    opener::reveal(&path).map_err(|e| e.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // Must be the first plugin: a second app launch focuses the existing
        // window instead of spawning a second sidecar that fights over the DB.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .menu(|app| {
            Menu::with_items(
                app,
                &[
                    &Submenu::with_items(
                        app,
                        "File",
                        true,
                        &[
                            &MenuItem::with_id(app, "add-folder", "Add Folder…", true, Some("CmdOrCtrl+O"))?,
                            &MenuItem::with_id(app, "rescan", "Rescan Library", true, Some("CmdOrCtrl+R"))?,
                            &PredefinedMenuItem::separator(app)?,
                            &MenuItem::with_id(app, "export", "Export Named People…", true, None::<&str>)?,
                            &MenuItem::with_id(app, "import", "Import Named People…", true, None::<&str>)?,
                            &PredefinedMenuItem::separator(app)?,
                            &PredefinedMenuItem::quit(app, Some("Quit faces-h"))?,
                        ],
                    )?,
                    &Submenu::with_items(
                        app,
                        "View",
                        true,
                        &[
                            &MenuItem::with_id(app, "view-gallery", "Gallery", true, Some("CmdOrCtrl+G"))?,
                            &MenuItem::with_id(app, "view-search", "Search", true, Some("CmdOrCtrl+F"))?,
                            &PredefinedMenuItem::separator(app)?,
                            &MenuItem::with_id(app, "theme-light", "Light Mode", true, None::<&str>)?,
                            &MenuItem::with_id(app, "theme-dark", "Dark Mode", true, None::<&str>)?,
                            &MenuItem::with_id(app, "theme-system", "Follow System", true, None::<&str>)?,
                        ],
                    )?,
                ],
            )
        })
        .on_menu_event(|app, event| {
            let _ = app.emit("menu-action", event.id().as_ref());
        })
        .plugin(
            tauri_plugin_log::Builder::new()
                .target(tauri_plugin_log::Target::new(
                    tauri_plugin_log::TargetKind::LogDir {
                        file_name: Some("app".into()),
                    },
                ))
                // Mirror shell logs to the webview (log://log events) so the
                // in-app activity log can show them tagged as [app] (#126).
                .target(tauri_plugin_log::Target::new(
                    tauri_plugin_log::TargetKind::Webview,
                ))
                .max_file_size(5 * 1024 * 1024)
                .rotation_strategy(tauri_plugin_log::RotationStrategy::KeepAll)
                .build(),
        )
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            get_sidecar_url,
            get_sidecar_token,
            open_in_viewer,
            reveal_in_explorer,
        ])
        .setup(|app| {
            // Clear any sidecar orphaned by a prior crash before starting ours,
            // so it can't hold the DB/WAL lock or shadow the new one.
            kill_orphaned_sidecars();

            let port = allocate_port();
            let token = generate_token();
            let url = format!("http://127.0.0.1:{port}");

            let data_dir = app
                .path()
                .app_data_dir()
                .unwrap_or_else(|_| std::path::PathBuf::from("."))
                .to_string_lossy()
                .to_string();

            let app_version = app.package_info().version.to_string();
            log::info!("faces-h starting — version={app_version} port={port} data_dir={data_dir}");

            let launch = SidecarLaunch {
                port,
                data_dir,
                app_version,
                token: token.clone(),
            };

            // Spawn the Python sidecar; the binary is resolved from externalBin in tauri.conf.json.
            let child = spawn_sidecar(app.handle(), &launch).map_err(|e| e.to_string())?;

            let sidecar_pid = child.pid();
            log::info!("sidecar spawned — pid={sidecar_pid} waiting for port {port}");

            app.manage(SidecarState {
                url: url.clone(),
                token: token.clone(),
                child: Mutex::new(Some(child)),
                pid: AtomicU32::new(sidecar_pid),
                shutting_down: AtomicBool::new(false),
            });

            // Health-check the sidecar in a background thread; emit "sidecar-ready"
            // once it accepts TCP connections, then keep supervising it (#119).
            // 180 s timeout: on first run after an upgrade Windows Defender scans
            // the PyInstaller binary; UPX is disabled so this now takes < 30 s,
            // but we keep a generous limit for slow / heavily locked-down machines.
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let start = std::time::Instant::now();
                if wait_for_port(port, Duration::from_secs(180)) {
                    let elapsed = start.elapsed().as_millis();
                    log::info!("sidecar ready on port {port} after {elapsed} ms");
                    let payload = serde_json::json!({ "url": url, "token": token });
                    let _ = handle.emit("sidecar-ready", payload);
                    watchdog_loop(handle, launch, url);
                } else {
                    log::error!("sidecar did not bind on port {port} within 180 s — giving up");
                    let _ = handle.emit("sidecar-error", "Engine failed to start after 3 min");
                    handle.exit(1);
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                let app = window.app_handle();
                if let Some(state) = app.try_state::<SidecarState>() {
                    log::info!("window closing — killing sidecar");
                    // Tell the watchdog this is a deliberate shutdown, then kill
                    // the full process tree so PyInstaller's bootstrap AND its
                    // Python worker subprocess are both terminated (#54).
                    state.shutting_down.store(true, Ordering::SeqCst);
                    kill_sidecar_tree(state.pid.load(Ordering::SeqCst));
                    if let Ok(mut guard) = state.child.lock() {
                        guard.take(); // drop the CommandChild handle
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn port_allocation_returns_nonzero_port() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        drop(listener);
        assert!(port > 0, "allocated port must be non-zero");
    }

    #[test]
    fn token_is_64_hex_chars_and_unique() {
        let a = generate_token();
        let b = generate_token();
        assert_eq!(a.len(), 64, "256 bits hex-encoded");
        assert!(a.chars().all(|c| c.is_ascii_hexdigit()));
        assert_ne!(a, b, "two tokens must never collide");
    }

    #[test]
    fn sidecar_url_format_is_correct() {
        let port: u16 = 51423;
        let url = format!("http://127.0.0.1:{port}");
        assert!(url.starts_with("http://127.0.0.1:"));
        assert!(url.ends_with("51423"));
    }

    #[test]
    fn sidecar_healthy_false_on_closed_port() {
        // Allocate a port and immediately free it — nothing listens there.
        let port = allocate_port();
        assert!(!sidecar_healthy(port), "closed port must report unhealthy");
    }

    #[test]
    fn sidecar_healthy_true_on_open_port() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        assert!(sidecar_healthy(port), "listening port must report healthy");
        drop(listener);
    }
}
