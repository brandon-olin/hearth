use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Manager};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_shell::{process::CommandChild, ShellExt};

/// Holds the spawned FastAPI sidecar process so we can kill it on exit.
struct ApiProcess(Arc<Mutex<Option<CommandChild>>>);

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(ApiProcess(Arc::new(Mutex::new(None))))
        .setup(|app| {
            // Open DevTools automatically so the app is inspectable.
            // Requires the "devtools" feature in Cargo.toml.
            if let Some(window) = app.get_webview_window("main") {
                window.open_devtools();
            }

            if let Err(e) = spawn_api_sidecar(app.handle()) {
                eprintln!("ERROR: failed to start API sidecar: {e}");
                // Show a dialog so the error is visible in release builds.
                let _ = app.dialog()
                    .message(format!("Failed to start API server:\n\n{e}"))
                    .title("Hearth — startup error")
                    .blocking_show();
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            // Kill the sidecar when the last window closes.
            if let tauri::WindowEvent::Destroyed = event {
                let app = window.app_handle();
                if app.webview_windows().is_empty() {
                    kill_api_sidecar(&app);
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running life dashboard");
}

/// Spawn the FastAPI sidecar and store the child handle.
///
/// The sidecar binary is named `life_dashboard_api` and must be placed in
/// `src-tauri/binaries/` as `life_dashboard_api-<target-triple>[.exe]`
/// (Tauri's sidecar naming convention).
///
/// Environment variables forwarded to the sidecar:
///   DATABASE_URL  — SQLite path in the app data directory
///   JWT_SECRET_KEY — generated on first launch, persisted in app data
///   UPLOAD_DIR    — upload directory in app data
fn spawn_api_sidecar(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let app_data = app.path().app_data_dir()?;
    std::fs::create_dir_all(&app_data)?;

    let db_path = app_data.join("life_dashboard.db");
    let upload_dir = app_data.join("uploads");
    std::fs::create_dir_all(&upload_dir)?;

    // Persist or generate a stable JWT secret key.
    let secret_path = app_data.join("jwt_secret.key");
    let jwt_secret = if secret_path.exists() {
        std::fs::read_to_string(&secret_path).unwrap_or_else(|_| new_secret())
    } else {
        let s = new_secret();
        let _ = std::fs::write(&secret_path, &s);
        s
    };

    let database_url = format!(
        "sqlite+aiosqlite:///{}",
        db_path.to_string_lossy()
    );

    let sidecar = app
        .shell()
        .sidecar("life_dashboard_api")?
        .env("DATABASE_URL", &database_url)
        .env("JWT_SECRET_KEY", &jwt_secret)
        .env("JWT_ALGORITHM", "HS256")
        .env("UPLOAD_DIR", upload_dir.to_string_lossy().as_ref())
        // "development" disables the Secure flag on the refresh cookie.
        // The sidecar serves over plain HTTP, so Secure cookies would be
        // silently rejected by the WebView, breaking token refresh.
        .env("ENVIRONMENT", "development")
        .env("LOG_LEVEL", "info")
        // Allow the Tauri WebView origin plus localhost for dev tools.
        .env("ALLOWED_ORIGINS", "tauri://localhost,http://localhost,http://localhost:1430")
        .env("HOST", "127.0.0.1")
        .env("PORT", "1338");

    let (_rx, child) = sidecar.spawn()?;

    let state = app.state::<ApiProcess>();
    *state.0.lock().unwrap() = Some(child);

    log::info!("FastAPI sidecar started — DATABASE_URL={}", database_url);
    Ok(())
}

/// Gracefully terminate the API sidecar.
fn kill_api_sidecar(app: &AppHandle) {
    let state = app.state::<ApiProcess>();
    if let Ok(mut guard) = state.0.lock() {
        if let Some(child) = guard.take() {
            let _ = child.kill();
            log::info!("FastAPI sidecar stopped");
        }
    };
}

/// Generate a random 32-byte hex JWT secret.
fn new_secret() -> String {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{Hash, Hasher};
    use std::time::{SystemTime, UNIX_EPOCH};

    // Simple secret generation without external crates.
    // For production hardening, replace with `rand` crate.
    let mut hasher = DefaultHasher::new();
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos()
        .hash(&mut hasher);
    std::process::id().hash(&mut hasher);
    format!("{:016x}{:016x}", hasher.finish(), hasher.finish().wrapping_mul(0xdeadbeefcafe))
}
