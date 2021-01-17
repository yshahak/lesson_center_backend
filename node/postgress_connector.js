const { Pool, Client } = require('pg')
// pools will use environment variables
// for connection information
const pool = new Pool({
  user: 'yaakov',
  host: 'localhost',
  database: 'lessons',
  password: '1234',
  port: 5432,
})
//pool.query('SELECT COUNT(*) FROM lessons', (err, res) => {
//  console.log(err, res)
//  pool.end()
//})


function getLastWeek() {
  var today = new Date();
  var lastWeek = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 7);
  return lastWeek;
}

const query = {
  text: 'SELECT * FROM categories where updatedat > $1',
  values: [getLastWeek()],
}
pool.query(query)
.then(res => console.log(res))
.catch(e => console.error(e));
pool.end();
//// you can also use async/await
//const res = await pool.query('SELECT NOW()')
//await pool.end()
//// clients will also use environment variables
//// for connection information
//const client = new Client()
//await client.connect()
//const res = await client.query('SELECT NOW()')
//await client.end()