import sqlite3
import os
import psycopg2.extras
from config import *
root_path = "%s/.." % os.path.dirname(os.path.realpath(__file__))
postgres = psycopg2.connect(**postgres_con)
sqlite_source = '%s/sqlite/lessons.db' % root_path
print(sqlite_source)
conn = sqlite3.connect(sqlite_source)


def create_lesson_table():
    c = conn.cursor()
    # Create table
    c.execute(str('''
                     DROP TABLE IF EXISTS lessons
                     '''))
    c.execute(str('''
                 CREATE TABLE lessons
                 (id INTEGER NON NULL PRIMARY KEY,
                 source TEXT,
                 title TEXT,
                 label TEXT,
                 subjectId INTEGER,
                 subject TEXT,
                 seriesId INTEGER,
                 series TEXT,
                 dateStr TEXT,
                 ravId INTEGER,
                 rav TEXT,
                 length TEXT,
                 videoUrl TEXT NULLABLE,
                 audioUrl TEXT NULLABLE,
                 timestamp INTEGER
                 )
                 '''))
    c.close()
    conn.commit()


def get_all_lessons():
    cursor = postgres.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('''
        select id,
                     source,
                     title,
                     label,
                     subjectid as "subjectId",
                     subject,
                     seriesid as "seriesId",
                     series,
                     datestr as "dateStr",
                     ravid as "ravId",
                     rav,
                     length,
                     videourl as "videoUrl",
                     audiourl as "audioUrl",
                     timestamp from lessons 
                     --limit 1
    ''')
    for row in cursor:
        body = {}
        for key,value in row.items():
            if isinstance(value, str):
                body[key] = value.encode().decode('utf-8')
            else:
                body[key] = value
            # print("{0}\t{1}\t{2}".format(key, type(value), value))
        convert(body)
    print('finished convert postgres to sqlite!')
    dest1 = '%s/files/public/lessons.db' % root_path
    with open(sqlite_source, 'rb') as src, open(dest1, 'wb') as dst:
        dst.write(src.read())
    dest2 = '%s/web/assets/assets/lessons.db' % root_path
    with open(sqlite_source, 'rb') as src, open(dest2, 'wb') as dst:
        dst.write(src.read())



def convert(row):
    c = conn.cursor()
    c.execute(str('''INSERT INTO lessons VALUES (
                     :id,
                     :source,
                     :title,
                     :label,
                     :subjectId,
                     :subject,
                     :seriesId,
                     :series,
                     :dateStr,
                     :ravId,
                     :rav,
                     :length,
                     :videoUrl,
                     :audioUrl,
                     :timestamp)
                                    '''), row)
    c.close()
    conn.commit()


def start_conversion():
    create_lesson_table()
    get_all_lessons()

if __name__ == '__main__':
    pass
    start_conversion()
