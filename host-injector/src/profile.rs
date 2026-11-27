//! Declarative Open Gate profile loading (serde over the repo's `profiles/*.json`).
//!
//! Unknown JSON fields (anchors, payload_ref, derivation, notes, …) are ignored, so
//! this stays in step with the richer profile files without duplicating every field.

use std::collections::HashMap;
use std::path::Path;

use serde::Deserialize;

use crate::{parse_hex_bytes, parse_u64, Error, Result};

#[derive(Debug, Deserialize)]
pub struct Profile {
    pub schema: String,
    pub name: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub output: Output,
    #[serde(default)]
    pub region_bases: HashMap<String, Option<String>>,
    #[serde(default)]
    pub steps: Vec<Step>,
    #[serde(default)]
    pub summary: String,
}

#[derive(Debug, Default, Deserialize)]
pub struct Output {
    #[serde(default)]
    pub width: u32,
    #[serde(default)]
    pub height: u32,
    #[serde(default)]
    pub aspect: String,
    #[serde(default)]
    pub fps: Vec<u32>,
}

#[derive(Debug, Deserialize)]
pub struct Step {
    pub id: String,
    #[serde(default)]
    pub label: String,
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub writes: Vec<Write>,
}

#[derive(Debug, Deserialize)]
pub struct Write {
    pub region: String,
    pub addr: String,
    pub len: u32,
    #[serde(default)]
    pub stock: Option<String>,
    #[serde(default)]
    pub target: Option<String>,
}

impl Profile {
    /// Load by name (looked up in `dir`) or by direct path to a `.json`.
    pub fn load(dir: &Path, name: &str) -> Result<Profile> {
        let direct = Path::new(name);
        let path = if direct.is_file() {
            direct.to_path_buf()
        } else {
            dir.join(format!("{name}.json"))
        };
        let text = std::fs::read_to_string(&path)
            .map_err(|e| Error::Io(format!("{}: {e}", path.display())))?;
        let prof: Profile = serde_json::from_str(&text)
            .map_err(|e| Error::Parse(format!("{}: {e}", path.display())))?;
        if prof.schema != "opengate-profile/1" {
            return Err(Error::Parse(format!(
                "{}: unsupported schema {:?}",
                path.display(),
                prof.schema
            )));
        }
        Ok(prof)
    }

    /// The mapped base for a region (`0` when null/absent).
    pub fn region_base(&self, region: &str) -> Result<u64> {
        match self.region_bases.get(region) {
            Some(Some(s)) => parse_u64(s),
            _ => Ok(0),
        }
    }

    /// Resolve a write's absolute virtual address.
    pub fn resolve(&self, w: &Write) -> Result<u64> {
        Ok(self.region_base(&w.region)? + parse_u64(&w.addr)?)
    }
}

impl Write {
    pub fn stock_bytes(&self) -> Result<Option<Vec<u8>>> {
        self.stock.as_deref().map(parse_hex_bytes).transpose()
    }
    pub fn target_bytes(&self) -> Result<Option<Vec<u8>>> {
        self.target.as_deref().map(parse_hex_bytes).transpose()
    }
}
