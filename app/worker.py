from collections import deque
from concurrent.futures import Future
from threading import Condition, RLock, Thread


class OperationCancelled(RuntimeError):
    pass


class OperationToken:
    def __init__(self, worker, generation):
        self.worker = worker
        self.generation = generation

    def check(self):
        with self.worker._gate:
            self._check_locked()

    def _check_locked(self):
        if self.worker._closed or self.generation != self.worker._generation:
            raise OperationCancelled("操作已停止")

    def dispatch(self, action):
        # Stop and native submission share this gate: no new command after stop returns.
        with self.worker._gate:
            self._check_locked()
            return action()


class SerialWorker:
    def __init__(self):
        self._gate = RLock()
        self._condition = Condition(self._gate)
        self._pending = deque()
        self._generation = 0
        self._stopped = False
        self._closed = False
        self._active = False
        self._thread = Thread(target=self._run, name="m4b-device", daemon=True)
        self._thread.start()

    @property
    def busy(self):
        with self._gate:
            return self._active or bool(self._pending)

    @property
    def stopped(self):
        with self._gate:
            return self._stopped

    def submit(self, action, *, resume=False):
        with self._condition:
            if self._closed:
                raise RuntimeError("程序正在关闭")
            if resume:
                if self._active or self._pending:
                    raise RuntimeError("请等待当前操作结束")
                self._stopped = False
            elif self._stopped:
                raise OperationCancelled("已停止，请手动重新连接后继续")
            if self._active or self._pending:
                raise RuntimeError("已有操作进行中，请等待完成")
            future = Future()
            self._pending.append((self._generation, action, future))
            self._condition.notify()
            return future

    def stop(self):
        cancelled = []
        with self._condition:
            self._stopped = True
            self._generation += 1
            while self._pending:
                _, _, future = self._pending.popleft()
                cancelled.append(future)
            self._condition.notify_all()
        for future in cancelled:
            future.set_exception(OperationCancelled("待执行操作已取消"))

    def close(self):
        self.stop()
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def _run(self):
        while True:
            with self._condition:
                while not self._pending and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return
                generation, action, future = self._pending.popleft()
                self._active = True
            try:
                token = OperationToken(self, generation)
                token.check()
                result = action(token)
                token.check()
            except Exception as error:
                # A failed operation must not leave the worker enabled for another command.
                self.stop()
                future.set_exception(error)
            else:
                future.set_result(result)
            finally:
                with self._gate:
                    self._active = False

