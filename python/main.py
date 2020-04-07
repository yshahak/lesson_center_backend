import sys
from arutz_meir_grabber import grab as grab_meir
from arutz_meir_grabber import grab_widgets as grab_meir_widgets
from bnei_david_grabber import grab, grab_main_page
from postgres_to_sql_converter import start_conversion

if __name__ == '__main__':
    if len(sys.argv) > 1:
        print('grabbing main page')
        grab_main_page()
        grab_meir_widgets()
    else:
        print('grabbing all')
        grab_meir()
        grab()
    start_conversion()
