var express = require('express');
var JSONbig = require('json-bigint');
const Router = require('express-promise-router');
const db = require('../db');
const router = new Router()
// export our router to be mounted by the parent application
module.exports = router

router.get('/', async (req, res) => {
    const {rows} = await db.query('SELECT * FROM labels;');
    if (rows.length === 0) {
        res.send({
            "mainPage": [],
            "lessons": [],
        });
        return;
    }
    const ids = rows.map(e => e["lessonId"]);

    const lessonQuery = ('SELECT * FROM lessons WHERE id = ANY($1)');
    const result = await db.query(lessonQuery, [ids])
    const lessons = result["rows"];
    const body = {
        "mainPage": rows,
        "lessons": lessons,
    };
    res.setHeader('Content-Type', 'application/json');
    res.send(JSONbig.stringify(body));
})

module.exports = router;
