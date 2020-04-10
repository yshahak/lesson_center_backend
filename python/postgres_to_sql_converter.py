import sqlite3
import os
import psycopg2.extras
from config import *

root_path = "%s/.." % os.path.dirname(os.path.realpath(__file__))
postgres = psycopg2.connect(**postgres_con)
sqlite_source = '%s/sqlite/lessons.db' % root_path
print(sqlite_source)
conn = sqlite3.connect(sqlite_source)


def create_sqlite_tables():
    c = conn.cursor()
    # Create table
    c.execute('''DROP TABLE IF EXISTS lessons''')
    c.execute('''DROP TABLE IF EXISTS ravs''')
    c.execute('''DROP TABLE IF EXISTS categories''')
    c.execute('''DROP TABLE IF EXISTS series''')
    c.execute('''DROP TABLE IF EXISTS labels''')
    c.execute(str('''
                 CREATE TABLE lessons
                 (id INTEGER NOT NULL PRIMARY KEY,
                 sourceId INTEGER NOT NULL,
                 originalId INTEGER NOT NULL,
                 title TEXT,
                 categoryId INTEGER,
                 seriesId INTEGER,
                 dateStr TEXT,
                 ravId INTEGER,
                 duration INTEGER,
                 videoUrl TEXT NULLABLE,
                 audioUrl TEXT NULLABLE,
                 timestamp INTEGER
                 );
                 '''))
    c.execute(str('''
                CREATE TABLE ravs(
                  id INTEGER NOT NULL PRIMARY KEY,
                  originalId INTEGER NOT NULL,
                  sourceId INTEGER NOT NULL,
                  totalCount INTEGER NOT NULL,
                  rav TEXT NOT NULL
                );'''))
    c.execute('''
                CREATE TABLE categories(
                  id INTEGER NOT NULL PRIMARY KEY,
                  originalId INTEGER NOT NULL,
                  sourceId INTEGER NOT NULL,
                  totalCount INTEGER NOT NULL,
                  category TEXT NOT NULL
                );
    ''')
    c.execute('''
                CREATE TABLE series(
                  id INTEGER NOT NULL PRIMARY KEY,
                  originalId INTEGER NOT NULL,
                  sourceId INTEGER NOT NULL,
                  totalCount INTEGER NOT NULL,
                  serie TEXT NOT NULL
                );
    ''')
    c.execute('''
                CREATE TABLE labels(
                  id SERIAL PRIMARY KEY,
                  sourceId INTEGER NOT NULL,
                  lessonId INTEGER NOT NULL,
                  label TEXT NOT NULL
                );
    ''')
    c.close()
    conn.commit()


def get_all_lessons():
    cursor = postgres.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('select id from categories')
    all_categories = [row['id'] for row in cursor]
    for category_id in all_categories:
        cursor.execute('''
            select id,
                         sourceid as "sourceId",
                         originalid as "originalId",
                         title,
                         categoryid as "categoryId",
                         seriesid as "seriesId",
                         datestr as "dateStr",
                         ravid as "ravId",
                         duration,
                         videourl as "videoUrl",
                         audiourl as "audioUrl",
                         timestamp 
                         FROM lessons
                         WHERE categoryid = %s 
                         LIMIT 100;
                         
        ''', (category_id,))
        for row in cursor:
            body = {}
            for key, value in row.items():
                if isinstance(value, str):
                    body[key] = value.encode().decode('utf-8')
                else:
                    body[key] = value
            convert(body)


def convert(row):
    c = conn.cursor()
    c.execute(str('''INSERT INTO lessons VALUES (
                     :id,
                     :sourceId,
                     :originalId,
                     :title,
                     :categoryId,
                     :seriesId,
                     :dateStr,
                     :ravId,
                     :duration,
                     :videoUrl,
                     :audioUrl,
                     :timestamp) ON CONFLICT DO NOTHING;
                                    '''), row)
    c.close()


def get_other_tables(table: str, col: str, col_id_name: str):
    cursor = postgres.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT id,originalid as "originalId",sourceid as "sourceId",totalcount as "totalCount",{0} FROM {1}'.format(col, table))
    # ids = []
    for row in cursor:
        body = {}
        for key, value in row.items():
            if isinstance(value, str):
                body[key] = value.encode().decode('utf-8')
            else:
                body[key] = value
        # ids.append(body['id'])
        convert_record(table, col, body)
    # get_lessons_for_type(ids, col_id_name)


def get_lessons_for_type(ids, col):
    cursor = postgres.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    for id in ids:
        cursor.execute('''
            select id,
                         sourceid as "sourceId",
                         originalid as "originalId",
                         title,
                         categoryid as "categoryId",
                         seriesid as "seriesId",
                         datestr as "dateStr",
                         ravid as "ravId",
                         duration,
                         videourl as "videoUrl",
                         audiourl as "audioUrl",
                         timestamp 
                         FROM lessons
                         WHERE {0} = %s 
                         LIMIT 10;
                         
        '''.format(col), (id,))
        for row in cursor:
            body = {}
            for key, value in row.items():
                if isinstance(value, str):
                    body[key] = value.encode().decode('utf-8')
                else:
                    body[key] = value
            convert(body)


def convert_record(table: str, col: str, record: dict):
    c = conn.cursor()
    c.execute(str('''INSERT INTO {0} VALUES (
                     :id,
                     :originalId,
                     :sourceId,
                     :totalCount,
                     :{1})
                                    '''.format(table, col)), record)
    c.close()


def copy_files():
    dest1 = '%s/files/public/lessons.db' % root_path
    with open(sqlite_source, 'rb') as src, open(dest1, 'wb') as dst:
        dst.write(src.read())
    dest2 = '%s/web/assets/assets/lessons.db' % root_path
    with open(sqlite_source, 'rb') as src, open(dest2, 'wb') as dst:
        dst.write(src.read())


def start_conversion():
    create_sqlite_tables()
    get_other_tables('categories', 'category', 'subjectid')
    get_other_tables('series', 'serie', 'seriesid')
    get_other_tables('ravs', 'rav', 'ravid')
    # get_all_lessons()
    conn.commit()
    copy_files()
    print('finished convert postgres to sqlite!')


def updateTotals(table:str, col:str):
    cursor = postgres.cursor()
    cursor.execute('SELECT id  FROM {}'.format(table))
    rows = cursor.fetchall()
    for row in rows:
        id = row[0]
        cursor.execute('select count(*) from lessons where {0} = %s'.format(col), (id,))
        total = cursor.fetchone()[0]
        cursor.execute('''UPDATE {0} SET totalcount = %s where id = %s'''.format(table), (total, id,))
    postgres.commit()


if __name__ == '__main__':
    start_conversion()
    # updateTotals('ravs', 'ravid')
    # updateTotals('series', 'seriesid')
    # updateTotals('categories', 'categoryid')
