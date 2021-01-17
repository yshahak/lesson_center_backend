//const Query = require('pg').Query;
//const submit = Query.prototype.submit;
//Query.prototype.submit = function() {
//  const text = this.text;
//  const values = this.values;
//  const query = values.reduce((q, v, i) => q.replace(`$${i + 1}`, v), text);
//  console.log(query);
//  submit.apply(this, arguments);
//};
const JSONbig = require('json-bigint');
const url = require('url');
const pg = require('pg');
const { Pool } = pg;
pg.types.setTypeParser(20, BigInt);
const pool = new Pool({
  user: 'yaakov',
  host: 'localhost',
  database: 'lessons',
  password: '1234',
  port: 5432,
})

module.exports = {
  query: (text, params) => pool.query(text, params),
  readTable:  async (req, res, queryText, tableName) => {
    const queryObject = url.parse(req.url, true).query;
    const timestamp = queryObject.timestamp || "0";
    const page = queryObject.page || "1";
    const limit = queryObject.limit || "200";
    const offset = (parseInt(page) - 1) * parseInt(limit);
    const {rows} = await pool.query(queryText, [timestamp, limit, offset])
    let timeQuery = await pool.query(`SELECT MAX(updatedat) as "lastRun" FROM ${tableName}`);
    const lastRun = timeQuery["rows"][0]["lastRun"].getTime();
    const body = {
      "entries": rows,
      "ts": lastRun,
    };
    res.setHeader('Content-Type', 'application/json');
    res.send(JSONbig.stringify(body));
  }
}