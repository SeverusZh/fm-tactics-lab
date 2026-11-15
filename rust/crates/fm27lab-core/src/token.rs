pub fn generate_token() -> Result<String, getrandom::Error> {
    let mut bytes = [0u8; 32];
    getrandom::getrandom(&mut bytes)?;
    let mut token = String::with_capacity(64);
    for byte in bytes {
        use std::fmt::Write;
        write!(&mut token, "{byte:02x}").expect("writing to a String cannot fail");
    }
    Ok(token)
}
