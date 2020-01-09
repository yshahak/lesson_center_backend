import sys
from bnei_david_grabber import grab, grab_main_page
from postgres_to_sql_converter import start_conversion

if __name__ == '__main__':
    if len(sys.argv) > 1:
        print('grabbing main page')
        grab_main_page()
    else:
        print('grabbing all')
        grab()
    start_conversion()
