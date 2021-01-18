const Router = require('express-promise-router');
const db = require('../db');
// create a new express-promise-router
// this has the same API as the normal express router except
// it allows you to use async functions as route handlers
const router = new Router()
// export our router to be mounted by the parent application
module.exports = router

router.get('/', async (req, res) => {
    await db.readTable(req, res, `SELECT * FROM categories WHERE extract(epoch from updatedat) * 1000 > $1 AND "totalCount" > 0 ORDER BY updatedat DESC LIMIT $2 OFFSET $3;`, "categories")
})

module.exports = router;