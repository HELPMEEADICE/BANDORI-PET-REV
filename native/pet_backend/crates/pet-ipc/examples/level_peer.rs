//! Non-graphical multi-process lifecycle test helper.
use pet_ipc::level::{LevelPublisher, LevelReader};
use std::io::{self, BufRead, Write};
use std::path::Path;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    let path = Path::new(args.get(2).ok_or("missing path")?);
    let mut writer = if args[1] == "producer" {
        Some(LevelPublisher::create(path)?)
    } else {
        None
    };
    let reader = if writer.is_none() {
        Some(LevelReader::attach(path)?)
    } else {
        None
    };
    println!("READY");
    io::stdout().flush()?;
    for line in io::stdin().lock().lines() {
        let line = line?;
        if line == "abort" {
            std::process::exit(13);
        }
        let mut fields = line.split_whitespace();
        if let Some(writer) = &mut writer {
            let peak = fields.next().ok_or("peak missing")?.parse()?;
            let stamp = fields.next().ok_or("timestamp missing")?.parse()?;
            println!("{}", writer.publish(peak, stamp)?);
        } else if let Some(reader) = &reader {
            println!("{}", reader.level(line.parse()?));
        }
        io::stdout().flush()?;
    }
    Ok(())
}
