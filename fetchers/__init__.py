# -*- coding: utf-8 -*-
"""소스별 수집 어댑터.

각 모듈은 `collect(conn, *, dry_run=False) -> FetchResult` 를 노출하며,
예외를 밖으로 던지지 않는다. 한 소스의 실패가 다른 소스를 막지 않게 하기 위해서다.
"""
