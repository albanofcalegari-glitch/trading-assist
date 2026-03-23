"""
Conexión a MySQL — trading-assist
"""
import pymysql
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config import MYSQL_CONFIG


def get_conn(autocommit: bool = True):
    conn = pymysql.connect(**MYSQL_CONFIG)
    conn.autocommit(autocommit)
    return conn
