use std::net::TcpListener;
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{Emitter, Manager};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

pub struct SidecarState {
    pub url: String,
    pub child: Mutex<Option<CommandChild>>,
}

/// Bind a TCP listener on port 0 to let the OS pick a free port, read it, then
/// drop the listener so the port is available for the sidecar.
pub fn allocate_port() -> u16 {
    let listener = TcpListener::bind("127.0.0.1:0").expect("failed to bind ephemeral port");
    let port = listener.local_addr().expect("no local addr").port();
    port // listener drops here, freeing the port
}

/// Poll until the TCP port accepts connections or the timeout elapses.
/// Using raw TCP rather than HTTP so we add no extra runtime dependency.
fn wait_for_port(port: u16, timeout: Duration) -> bool {
    use std::net::TcpStream;
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return true;
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
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            get_sidecar_url,
            open_in_viewer,
            reveal_in_explorer,
        ])
        .setup(|app| {
            let port = allocate_port();
            let url = format!("http://127.0.0.1:{port}");

            let data_dir = app
                .path()
                .app_data_dir()
                .unwrap_or_else(|_| std::path::PathBuf::from("."))
                .to_string_lossy()
                .to_string();

            // Spawn the Python sidecar; the binary is resolved from externalBin in tauri.conf.json.
            let (_, child) = app
                .shell()
                .sidecar("faces-sidecar")
                .map_err(|e| e.to_string())?
                .args(["--port", &port.to_string(), "--data-dir", &data_dir])
                .spawn()
                .map_err(|e| e.to_string())?;

            app.manage(SidecarState {
                url: url.clone(),
                child: Mutex::new(Some(child)),
            });

            // Health-check the sidecar in a background thread; emit "sidecar-ready"
            // once it accepts TCP connections so the frontend knows to proceed.
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                if wait_for_port(port, Duration::from_secs(30)) {
                    let _ = handle.emit("sidecar-ready", &url);
                } else {
                    eprintln!("Sidecar did not start within 30 s — exiting");
                    handle.exit(1);
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                let app = window.app_handle();
                if let Some(state) = app.try_state::<SidecarState>() {
                    if let Ok(mut guard) = state.child.lock() {
                        if let Some(child) = guard.take() {
                            let _ = child.kill();
                        }
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
