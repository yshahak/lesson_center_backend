import psycopg2.extras
from config import *


def get_parash():
    postgres = psycopg2.connect(**postgres_con)
    cursor = postgres.cursor()
    insert_cursor = postgres.cursor()
    cursor.execute('select id,title from lessons where "title" like %s;', ("%משפטים%",))
    for row in cursor.fetchall():
        print(row)
        insert_cursor.execute('''INSERT INTO labels (label,"sourceId","lessonId") VALUES(%s,%s,%s);''',
                              ('פרשת משפטים', 400, row[0]))
    insert_cursor.close()
    cursor.close()
    postgres.commit()
    postgres.close()


if __name__ == "__main__":
    pass
    get_parash()
