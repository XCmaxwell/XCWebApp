import logging; logging.basicConfig(level=logging.INFO)

import asyncio, os, json, time
from datetime import datetime

from aiohttp import web

def index(request):
    #python3 不加content_type 下载文件非直接浏览 
    return web.Response(body=b'<h1>Awesome</h1>', content_type='text/html')

# python2 写法，3.8版本已废弃
# @asyncio.coroutine 
# def init(loop):
async def init (loop):
    app = web.Application(loop=loop)
    app.router.add_route('GET', '/', index)
    # srv = yield from loop.create_server(app.make_handler(), '127.0.0.1', 9000)
    srv = await loop.create_server(app.make_handler(), '127.0.0.1', 9000)
    logging.info('server started at http://127.0.0.1:9000...')
    return srv

loop = asyncio.get_event_loop()
loop.run_until_complete(init(loop))
loop.run_forever()