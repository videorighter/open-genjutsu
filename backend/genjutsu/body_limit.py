from starlette.responses import JSONResponse


class BodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    def __init__(self, app, upload_limit):
        self.app = app
        self.upload_limit = upload_limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self.upload_limit if scope["path"] == "/api/assets" else 2 * 1024 * 1024
        consumed = 0
        started = False

        async def checked_receive():
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > limit:
                    raise BodyTooLarge()
            return message

        async def checked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        exceeded = False
        original_receive = checked_receive

        async def bounded_receive():
            nonlocal exceeded
            try:
                return await original_receive()
            except BodyTooLarge:
                exceeded = True
                raise

        async def bounded_send(message):
            if exceeded:
                if not started:
                    await JSONResponse(
                        {"detail": "요청 크기가 제한을 초과했습니다."}, status_code=413
                    )(scope, receive, checked_send)
                return
            await checked_send(message)

        try:
            await self.app(scope, bounded_receive, bounded_send)
        except BodyTooLarge:
            if not started:
                await JSONResponse(
                    {"detail": "요청 크기가 제한을 초과했습니다."}, status_code=413
                )(scope, receive, send)
