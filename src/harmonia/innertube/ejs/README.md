# YouTube player challenge solver

`core.min.js` and `lib.min.js` are the solver of [yt-dlp/ejs](https://github.com/yt-dlp/ejs)
0.8.0, as published in the `yt-dlp-ejs` package, unchanged. They are public domain
(Unlicense, see `LICENSE`); `lib.min.js` bundles meriyah (ISC) and astring (MIT),
whose notices are in its header.

`innertube/challenges.py` runs them with the YouTube player script to answer the `n` and
`sig` challenges of the encrypted stream URLs that age-restricted tracks get. When YouTube
changes its player so that they stop working, update both files from a newer `yt-dlp-ejs`
release and the version above.
