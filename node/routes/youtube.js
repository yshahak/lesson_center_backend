var JSONbig = require('json-bigint');
const Router = require('express-promise-router');
const router = new Router()
const url = require('url');
const ytdl = require('ytdl-core');

// export our router to be mounted by the parent application
module.exports = router

router.get('/', async (req, res) => {
    const queryObject = url.parse(req.url, true).query;
    const videoUrl = queryObject.url;
    const info = await ytdl.getInfo(videoUrl);
    let audioFormats = ytdl.filterFormats(info.formats, 'audioonly');
    const audioUrl = audioFormats[0]['url'];
    const body = {
        "audioUrl": audioUrl,
    };
    res.setHeader('Content-Type', 'application/json');
    res.send(JSONbig.stringify(body));
})
module.exports = router;
