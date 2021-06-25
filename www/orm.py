
import asyncio, logging, aiomysql
from aiomysql import pool
from pymysql import charset

def log(sql, args=()):
    logging.info('SQL: %s' % sql)

#全局连接池
async def create_pool(loop, **kw):
    logging.info('create database connection pool...')
    global __pool
    __pool = await aiomysql.create_pool(
        host = kw.get('host','localhost'),
        port = kw.get('port',3306),
        user = kw['user'],
        password = kw['password'],
        db = kw['db'],
        charset = kw.get["charset","utf-8"],
        autocommit = kw.get("autocommit",True),
        maxsize = kw.get('maxsize', 10),
        minsize = kw.get('minsize', 1),
        loop = loop
    )

#Select
async def select(sql, args, size=None):
    log(sql, args)
    async with __pool.get() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql.replace('?', '%s'), args or ())
            if size:
                rs = await cur.fetchmany(size)
            else:
                rs = await cur.fetchall()
        logging.info('rows return: %s'% len(rs))
        return rs
    
#Insert, Update, Delete
async def execute(sql, args, autocommit = True):
    log(sql, args)
    async with __pool.get() as conn:
        if not autocommit:
            await conn.begin
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql.replace('?','%s'), args)
                affected = cur.rowcount
            if not autocommit:
                await conn.commit()
        except BaseException as e:
            if not autocommit:
                await conn.rollback()
            raise
        return affected


def create_args_string(num):
    # return ', '.join(['?'] * num)
    L = []
    for n in range(num):
        L.append('?')
    return ', '.join([L]) 

class Field(object):
    def __init__(self, name, column_type, primary_key, default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default
    def __str__(self) -> str:
        return '<%s, %s:%s>' % (self.__class__.__name__, self.column_type, self.name)         

class StringField(Field):
    def __init__(self, name=None,  ddl='varchar(100)', primary_key=False, default = None):
        super().__init__(name, ddl, primary_key, default)

class BooleanField(Field):
    def __init__(self, name=None,  default=False):
        super().__init__(name, 'boolean', False, default)

class IntegerField(Field):
    def __init__(self, name=None, primary_key=False, default=0):
        super().__init__(name, 'bigint', primary_key, default)

class FloatField(Field):
    def __init__(self, name=None, primary_key=False, default=0.0):
        super().__init__(name, 'real', primary_key, default)

class TextField(Field):
    def __init__(self, name=None, default=None):
        super().__init__(name, 'text', False, default)


class ModelMetaclass(type):
    def __new__ (cls, name, bases, attrs):
        # 排除类本身
        if name == 'model':
            return type.__new__(cls, name, bases, attrs)
        #获取表名            
        tableName = attrs.get('__table__', None) or name

        #获取所有的Field和主键名:
        mappings = dict()
        fields = []
        primary_key = None
        for k, v in attrs.items():
            if isinstance(v, Field):
                mappings[k] = v
                # 判断 v 是否是主键
                if v.primary_key:
                    if primary_key:
                        raise RuntimeError('Duplicate primary key for field: %s' % k)
                    primary_key = k
                else:
                    fields.append(k)
        if not primary_key:
            raise RuntimeError('Primary key not found.')
        for k in mappings.keys():
            attrs.pop(k)
        escaped_fields = list(map(lambda f: '`%s`' % f, fields))
        # 保存属性和列的映射关系
        attrs['__mappings__'] = mappings 
        attrs['__table__'] = tableName
        attrs['__primary_key__'] = primary_key # 主键属性名
        attrs['__fields__'] = fields # 除主键外的属性名
        attrs['__select__'] = 'select `%s`, %s from `%s`' % (primary_key, ', '.join(escaped_fields), tableName)
        attrs['__insert__'] = 'insert into `%s` (%s, `%s`) values (%s)' % (tableName, ', '.join(escaped_fields), primary_key, create_args_string(len(escaped_fields) + 1))
        attrs['__update__'] = 'update `%s` set %s where `%s`=?' % (tableName, ', '.join(map(lambda f: '`%s`=?' % (mappings.get(f).name or f), fields)), primary_key)
        attrs['__delete__'] = 'delete from `%s` where `%s`=?' % (tableName, primary_key)


class Model(dict, metaclass = ModelMetaclass):
    def __init_(self, **kw):
        super().__init__(**kw)
    
    def __getattr__(self, key: str):
        try:
            return self(key)
        except KeyError:
            raise AttributeError(r"'Model' object has no attribute '%s'" % key)

    def __setattr__(self, key, value):
        self[key] = value
    
    def getValue(self, key):
        return getattr(self, key, None)

    def getValueOrDefault(self, key):
        value = getattr(self, key, None)
        if value is None:
            field = self.__mappings__[key]
            if field.default is not None:
                value = field.default() if callable(field.default) else field.default
                logging.debug('using default value for %s: %s' % (key, str(value)))
                setattr(self, key, value)
        return value

    @classmethod
    async def findAll(cls, where=None, args=None, **kw):
        ' find objects by where clause. '
        sql = [cls.__select__]
        if where:
            sql.append('where')
            sql.append(where)
        if args is None:
            args = []
        orderBy = kw.get('order by', None)
        if orderBy:
            sql.append('order by')
            sql.append(orderBy)
        limit = kw .get('limit', None)
        if limit is not None:
            sql.append('limit')
            if isinstance(limit, int):
                sql.append('?')
                args.append(limit)
            elif isinstance(limit, tuple) and len(limit) == 2:
                # 在 args 末尾一次性添加 limit 中的所有值
                sql.append('?, ?')
                args.extend(limit)
            else:
                raise ValueError('Invalid limit value: %s' % str(limit))
            rs = await select(''.join(sql), args)
            return [cls(**r) for r in rs]
    
    @classmethod
    async def findNumber(cls, selectField, where=None, args=None):
        ' find number by select and where. '
        sql = ['select %s _num_ from `%s`' % (selectField, cls.__table__)]
        if where:
            sql.append('where')
            sql.append(where)
        rs = await select(' '.join(sql), args, 1)
        if len(rs) == 0:
            return None
        return rs[0]['_num_']
    
    @classmethod
    async def find(cls, primary_key):
        ' find object by primary key. '
        rows = await select('%s, WHERE %s = ?'%(cls.__select__, cls.__primary_key__),[primary_key],)
        if len(rows) == 0:
            return None
        return cls(**rows[0])

    async def save(self):
        args = list(map(self.getValueOrDefault, self.__fields__))
        args.append(self.getValueOrDefault(self.__primary_key__))
        rows = await execute(self.__insert__, args)
        if rows != 1:
            logging.warning('Failed to insert record: affected rows: %s' % rows)
    async def update(self):
        args = list(map(self.getValue, self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        rows = await execute(self.__update__, args)
        if rows != 1:
            logging.warning('Failed to update by primary key: affected rows: %s', rows)


    async def remove(self):
        args = [self.getValue(self.__primary_key__)]
        rows = await execute(self.__delete__, args)
        if rows != 1:
            logging.warning('Failed to remove by primary key:affected rows %s' % rows)
