#[cxx_qt::bridge]
pub mod ffi {
    unsafe extern "C++" {
        include!("cxx-qt-lib/qstring.h");
        type QString = cxx_qt_lib::QString;
    }

    extern "RustQt" {
        #[qobject]
        #[qproperty(QString, status)]
        #[namespace = "bandori"]
        type Backend = super::BackendRust;

        #[qinvokable]
        #[cxx_name = "loadConfig"]
        fn load_config(self: Pin<&mut Self>, path: &QString) -> bool;
    }
}

use bandori_core::config::ConfigDocument;
use core::pin::Pin;
use cxx_qt_lib::QString;
use std::path::Path;

pub struct BackendRust {
    status: QString,
}

impl Default for BackendRust {
    fn default() -> Self {
        Self {
            status: QString::from("Rust core ready"),
        }
    }
}

impl ffi::Backend {
    pub fn load_config(mut self: Pin<&mut Self>, path: &QString) -> bool {
        match ConfigDocument::load(Path::new(&path.to_string())) {
            Ok(config) => {
                let status = format!(
                    "Rust core ready · {} configuration keys",
                    config.values().len()
                );
                self.as_mut().set_status(QString::from(&status));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Configuration error: {error}")));
                false
            }
        }
    }
}
