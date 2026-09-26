use std::env;
use std::ffi::{c_char, c_int, c_void, CString};
use std::path::PathBuf;

unsafe extern "C" {
    fn dlopen(path: *const c_char, mode: c_int) -> *mut c_void;
    fn dlsym(handle: *mut c_void, symbol: *const c_char) -> *mut c_void;
}

fn run() -> Result<i32, String> {
    let executable = env::current_exe().map_err(|error| error.to_string())?;
    let contents = executable
        .parent()
        .and_then(|path| path.parent())
        .ok_or("application bundle has no Contents directory")?;
    let library = contents.join("lib/libpython3.12.dylib");
    let library_path = CString::new(library.to_string_lossy().as_bytes())
        .map_err(|error| error.to_string())?;
    let handle = unsafe { dlopen(library_path.as_ptr(), 0x2 | 0x8) };
    if handle.is_null() {
        return Err(format!("cannot load bundled Python: {}", library.display()));
    }

    let symbol = unsafe { dlsym(handle, c"Py_BytesMain".as_ptr()) };
    if symbol.is_null() {
        return Err("bundled Python has no Py_BytesMain".to_owned());
    }

    env::set_var("PYTHONHOME", contents);
    env::set_var("PYTHONNOUSERSITE", "1");
    env::set_var("PYTHONDONTWRITEBYTECODE", "1");
    env::set_var(
        "PYTHONPATH",
        PathBuf::from(contents)
            .join("lib/python3.12/site-packages"),
    );

    let program = CString::new("").map_err(|error| error.to_string())?;
    let mut arguments = [program.as_ptr() as *mut c_char];
    let python_main: unsafe extern "C" fn(c_int, *mut *mut c_char) -> c_int =
        unsafe { std::mem::transmute(symbol) };
    Ok(unsafe { python_main(1, arguments.as_mut_ptr()) })
}

fn main() {
    match run() {
        Ok(code) => std::process::exit(code),
        Err(error) => {
            eprintln!("JevFeishu launcher: {error}");
            std::process::exit(1);
        }
    }
}
