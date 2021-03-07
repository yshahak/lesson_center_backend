//var express = require('express');
//var router = express.Router();
//
///* GET home page. */
//router.get('/', function(req, res, next) {
//  res.render('index', { title: 'Express' });
//});
//
//module.exports = router;

// ./routes/index.js
const lessons = require('./lessons');
const categories = require('./cateogries');
const series = require('./series');
const ravs = require('./ravs');
const sources = require('./sources');
const labels = require('./labels');
const youtube = require('./youtube');
module.exports = app => {
  app.use('/lessons', lessons);
  app.use('/categories', categories);
  app.use('/series', series);
  app.use('/ravs', ravs);
  app.use('/sources', sources);
  app.use('/labels', labels);
  app.use('/youtube', youtube);
}