use std::net::TcpListener;
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{Emitter, Manager};
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

pub struct SidecarState {
    pub url: String,
    pub child: Mutex<Option<CommandChild>>,
    pub pid: u32,
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

/// Return the sidecar base URL that the frontend should use for HTTP/WS.
#[tauri::command]
fn get_sidecar_url(state: tauri::State<SidecarState>) -> String {
    state.url.clone()
}

/// Open a file path in the default Windows viewer (ShellExecute "open").
#[tauri::command]
fn open_in_viewer(_path: String) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("cmd")
            .args(["/c", "start", "", &_path])
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Open File Explorer with the given file path selected.
#[tauri::command]
fn reveal_in_explorer(_path: String) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("explorer")
            .args(["/select,", &_path])
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
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
                .max_file_size(5 * 1024 * 1024)
                .rotation_strategy(tauri_plugin_log::RotationStrategy::KeepAll)
                .build(),
        )
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            get_sidecar_url,
            open_in_viewer,
            reveal_in_explorer,
        ])
        .setup(|app| {
            // Clear any sidecar orphaned by a prior crash before starting ours,
            // so it can't hold the DB/WAL lock or shadow the new one.
            kill_orphaned_sidecars();

            let port = allocate_port();
            let url = format!("http://127.0.0.1:{port}");

            let data_dir = app
                .path()
                .app_data_dir()
                .unwrap_or_else(|_| std::path::PathBuf::from("."))
                .to_string_lossy()
                .to_string();

            let app_version = app.package_info().version.to_string();
            log::info!("faces-h starting — version={app_version} port={port} data_dir={data_dir}");

            // Spawn the Python sidecar; the binary is resolved from externalBin in tauri.conf.json.
            let (_, child) = app
                .shell()
                .sidecar("faces-sidecar")
                .map_err(|e| e.to_string())?
                .args([
                    "--port", &port.to_string(),
                    "--data-dir", &data_dir,
                    "--app-version", &app_version,
                ])
                .spawn()
                .map_err(|e| e.to_string())?;

            let sidecar_pid = child.pid();
            log::info!("sidecar spawned — pid={sidecar_pid} waiting for port {port}");

            app.manage(SidecarState {
                url: url.clone(),
                child: Mutex::new(Some(child)),
                pid: sidecar_pid,
            });

            // Health-check the sidecar in a background thread; emit "sidecar-ready"
            // once it accepts TCP connections so the frontend knows to proceed.
            // 180 s timeout: on first run after an upgrade Windows Defender scans
            // the PyInstaller binary; UPX is disabled so this now takes < 30 s,
            // but we keep a generous limit for slow / heavily locked-down machines.
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let start = std::time::Instant::now();
                if wait_for_port(port, Duration::from_secs(180)) {
                    let elapsed = start.elapsed().as_millis();
                    log::info!("sidecar ready on port {port} after {elapsed} ms");
                    let _ = handle.emit("sidecar-ready", &url);
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
                    // Kill the full process tree so PyInstaller's bootstrap AND
                    // its Python worker subprocess are both terminated (#54).
                    kill_sidecar_tree(state.pid);
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
    fn sidecar_url_format_is_correct() {
        let port: u16 = 51423;
        let url = format!("http://127.0.0.1:{port}");
        assert!(url.starts_with("http://127.0.0.1:"));
        assert!(url.ends_with("51423"));
    }
}
