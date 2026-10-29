//! XDG desktop autostart, effective on the next graphical login.

use std::path::Path;
#[cfg(target_os = "linux")]
use std::{io, path::PathBuf};

#[cfg(target_os = "linux")]
fn path() -> io::Result<PathBuf> {
    let config = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".config")))
        .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound, "HOME is not set"))?;
    Ok(config.join("autostart/io.github.bandori-pet-lite.desktop"))
}

// Exec arguments have two escape layers: command quoting, then desktop-entry
// string escaping. No shell evaluates this command. Escape literal field codes.
fn exec_argument(value: &str) -> String {
    let mut quoted = String::from("\"");
    for character in value.chars() {
        match character {
            '\\' | '"' | '`' | '$' => {
                quoted.push('\\');
                quoted.push(character);
            }
            '%' => quoted.push_str("%%"),
            _ => quoted.push(character),
        }
    }
    quoted.push('"');
    quoted
        .replace('\\', "\\\\")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
        .replace('\t', "\\t")
}

fn desktop_entry(exe: &Path, root: Option<&Path>) -> String {
    let mut command = String::from("env");
    if let Some(root) = root {
        command.push(' ');
        command.push_str(&exec_argument(&format!(
            "BANDORI_PET_ROOT={}",
            root.display()
        )));
    }
    command.push(' ');
    command.push_str(&exec_argument(&exe.to_string_lossy()));
    format!(
        "[Desktop Entry]\nType=Application\nName=BANDORI-PET-LITE\nExec={command}\nTerminal=false\nStartupNotify=false\n"
    )
}

#[cfg(target_os = "linux")]
fn root_override() -> io::Result<Option<PathBuf>> {
    std::env::var_os(pet_config::paths::ROOT_ENV)
        .map(|root| std::env::current_dir().map(|directory| directory.join(root)))
        .transpose()
}

#[cfg(target_os = "linux")]
pub(crate) fn enabled(exe: &Path) -> bool {
    let Ok(root) = root_override() else {
        return false;
    };
    path()
        .and_then(std::fs::read_to_string)
        .is_ok_and(|contents| contents == desktop_entry(exe, root.as_deref()))
}

#[cfg(target_os = "linux")]
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
    let root = root_override()?;
    std::fs::create_dir_all(path.parent().expect("autostart directory"))?;
    std::fs::write(path, desktop_entry(exe, root.as_deref()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn desktop_exec_preserves_spaces_and_escapes_shell_and_field_characters() {
        let contents = desktop_entry(
            Path::new("/opt/Bandori Pet/bandori-pet"),
            Some(Path::new("/data/100% $models`\"\\")),
        );
        assert!(contents.contains("Exec=env \"BANDORI_PET_ROOT=/data/100%% \\\\$models\\\\`\\\\\"\\\\\\\\\" \"/opt/Bandori Pet/bandori-pet\"\n"));
        assert!(!desktop_entry(Path::new("/app/bandori-pet"), None).contains("BANDORI_PET_ROOT"));
        assert_eq!(exec_argument("line1\nline2"), "\"line1\\nline2\"");
    }
}
