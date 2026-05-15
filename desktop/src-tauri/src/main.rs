// Prevents an additional console window on Windows in release builds.
// Has no effect on other platforms.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    life_dashboard_lib::run()
}
