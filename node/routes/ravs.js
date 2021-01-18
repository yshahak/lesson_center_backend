const db = require('../db');

const Router = require('express-promise-router');
// create a new express-promise-router
// this has the same API as the normal express router except
// it allows you to use async functions as route handlers
const router = new Router()
// export our router to be mounted by the parent application
module.exports = router

router.get('/', async (req, res) => {
    await db.readTable(req, res, `SELECT * FROM ravs WHERE extract(epoch from updatedat) * 1000 > $1 AND "totalCount" > 0 ORDER BY updatedat DESC LIMIT $2 OFFSET $3;`, "ravs")
})

module.exports = router;