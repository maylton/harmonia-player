.pragma library

function highResolutionSource(value, size) {
    if (!value)
        return ""

    let result = String(value)
    const target = Math.max(128, Math.round(size || 1024))

    // YouTube Music artist/album artwork commonly exposes a resizable
    // googleusercontent/ggpht URL. Ask the server for enough pixels for
    // large covers instead of upscaling the small shelf thumbnail.
    if (result.indexOf("googleusercontent.com") >= 0 || result.indexOf("ggpht.com") >= 0) {
        result = result.replace(/=w\d+/, "=w" + target)
        result = result.replace(/-h\d+/, "-h" + target)
        result = result.replace(/=s\d+/, "=s" + target)
    }

    // Video thumbnails may have a max-resolution variant. Components keep
    // the original URL as a fallback when that variant is unavailable.
    if (result.indexOf("ytimg.com/") >= 0) {
        result = result.replace(/\/(?:default|mqdefault|hqdefault|sddefault)\.jpg(?:\?.*)?$/,
                                "/maxresdefault.jpg")
    }

    return result
}
