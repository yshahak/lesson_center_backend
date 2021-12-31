import psycopg2.extras
from config import *


def get_parash():
    postgres = psycopg2.connect(**postgres_con)
    cursor = postgres.cursor()
    insert_cursor = postgres.cursor()
    insert_cursor.execute('delete from labels where "sourceId" = 400;')
    cursor.execute('select id,title from lessons where "title" like %s or "title" like %s or "title" like %s ;', ("%וארא%", "%מצבדגבדגבדגורע%", "%בדגבגדבדגבד%", ))
    for row in cursor.fetchall():
        print(row)
        insert_cursor.execute('''INSERT INTO labels (label,"sourceId","lessonId") VALUES(%s,%s,%s);''',
                              ('פרשת וארא', 400, row[0]))
    cursor.execute('select * from labels where "sourceId" = 400 limit 1;')
    for row in cursor.fetchall():
        print(row)
    insert_cursor.close()
    cursor.close()
    postgres.commit()
    postgres.close()


def get_chag():
    postgres = psycopg2.connect(**postgres_con)
    cursor = postgres.cursor()
    insert_cursor = postgres.cursor()
    insert_cursor.execute('delete from labels where "sourceId" = 500;')
    cursor.execute('select id,title,"dateStr" from lessons where "title" like %s or "title" like %s group by id order by timestamp desc;', ("%gtghrtg%", "%ליבגבדגבדגבדסדר%", ))
    for row in cursor.fetchall():
        print(row)
        insert_cursor.execute('''INSERT INTO labels (label,"sourceId","lessonId") VALUES(%s,%s,%s);''',
                              ('שיעורים לחנוכה', 500, row[0]))
    insert_cursor.close()
    cursor.close()
    postgres.commit()
    postgres.close()


if __name__ == "__main__":
    pass
    get_parash()
    # get_chag()
