const Router = require('express-promise-router');
const db = require('../db');
// create a new express-promise-router
// this has the same API as the normal express router except
// it allows you to use async functions as route handlers
const router = new Router()
// export our router to be mounted by the parent application
module.exports = router

router.get('/', async (req, res) => {
    await db.readTable(req, res, `SELECT * FROM lessons WHERE extract(epoch from updatedat) * 1000  > $1 ORDER BY updatedat DESC LIMIT $2 OFFSET $3;`, "lessons")
})

module.exports = router;

var updatePostgress = '' +
    'alter table labels rename COLUMN lessonid To "lessonId";";\n' +
    'alter table labels rename COLUMN sourceid To "sourceId";\n' +
    'alter table lessons rename COLUMN sourceid To "sourceId";\n' +
    'alter table lessons rename COLUMN originalid To "originalId";\n' +
    'alter table lessons rename COLUMN categoryid To "categoryId";\n' +
    'alter table lessons rename COLUMN seriesId To "seriesId";\n' +
    'alter table lessons rename COLUMN ravid To "ravId";\n' +
    'alter table lessons rename COLUMN datestr To "dateStr";\n' +
    'alter table lessons rename COLUMN videourl To "videoUrl";\n' +
    'alter table lessons rename COLUMN audiourl To "audioUrl";\n' +
    'alter table categories rename COLUMN originalid To "originalId";\n' +
    'alter table categories rename COLUMN sourceid To "sourceId";\n' +
    'alter table categories rename COLUMN totalcount To "totalCount";\n' +
    'alter table series rename COLUMN originalid To "originalId";\n' +
    'alter table series rename COLUMN sourceid To "sourceId";\n' +
    'alter table series rename COLUMN totalcount To "totalCount";\n' +
    'alter table ravs rename COLUMN originalid To "originalId";\n' +
    'alter table ravs rename COLUMN sourceid To "sourceId";\n' +
    'alter table ravs rename COLUMN totalcount To "totalCount";\n' +

    '';