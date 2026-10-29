//! Per-user macOS login startup. LaunchAgents are loaded on the next login.

use std::path::Path;
#[cfg(target_os = "macos")]
use std::{io, path::PathBuf};

const LABEL: &str = "io.github.bandori-pet-lite";

#[cfg(target_os = "macos")]
fn path() -> io::Result<PathBuf> {
    std::env::var_os("HOME")
        .map(|home| {
            PathBuf::from(home)
                .join("Library/LaunchAgents")
                .join(format!("{LABEL}.plist"))
        })
        .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound, "HOME is not set"))
}

fn xml_escape(text: &str) -> String {
    text.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}

fn plist(exe: &Path, root: Option<&Path>) -> String {
    let executable = xml_escape(&exe.to_string_lossy());
    let environment = root.map_or_else(String::new, |root| {
        format!(
            "<key>EnvironmentVariables</key><dict><key>BANDORI_PET_ROOT</key><string>{}</string></dict>",
            xml_escape(&root.to_string_lossy())
        )
    });
    format!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n\
         <!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n\
         <plist version=\"1.0\"><dict>\n\
         <key>Label</key><string>{LABEL}</string>\n\
         <key>ProgramArguments</key><array><string>{executable}</string></array>\n\
         <key>RunAtLoad</key><true/>\n\
         <key>LimitLoadToSessionType</key><string>Aqua</string>\n\
         {environment}\n</dict></plist>\n"
    )
}

#[cfg(target_os = "macos")]
pub(crate) fn enabled(exe: &Path) -> bool {
    let root = std::env::var_os(pet_config::paths::ROOT_ENV).map(PathBuf::from);
    path()
        .and_then(std::fs::read_to_string)
        .is_ok_and(|contents| contents == plist(exe, root.as_deref()))
}

#[cfg(target_os = "macos")]
pub(crate) fn set_enabled(exe: &Path, enabled: bool) -> io::Result<()> {
    let path = path()?;
    if !enabled {
        return match std::fs::remove_file(path) {
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
            result => result,
        };
    }
    if !exe.is_absolute() || !exe.is_file() {
        return Err(io::Error::new(
            io::ErrorKind::NotFound,
            "autostart executable is missing",
        ));
    }
    let root = std::env::var_os(pet_config::paths::ROOT_ENV).map(PathBuf::from);
    std::fs::create_dir_all(path.parent().expect("LaunchAgents directory"))?;
    std::fs::write(path, plist(exe, root.as_deref()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn launch_arguments_preserve_spaces_and_escape_xml() {
        let contents = plist(
            Path::new("/Applications/Bandori & Friends.app/Contents/MacOS/bandori-pet"),
            Some(Path::new("/Users/test/Models <backup>")),
        );
        assert!(contents.contains("<array><string>/Applications/Bandori &amp; Friends.app/Contents/MacOS/bandori-pet</string></array>"));
        assert!(contents.contains("/Users/test/Models &lt;backup&gt;"));
        assert!(contents.contains("<key>RunAtLoad</key><true/>"));
        assert!(!plist(Path::new("/app/bandori-pet"), None).contains("EnvironmentVariables"));
    }
}
