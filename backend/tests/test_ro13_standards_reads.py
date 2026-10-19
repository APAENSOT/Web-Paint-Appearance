"""RO13 -- every signed-in role reads the Standard pages; only Admin changes them.

* ``GET /standards/catalogue`` and ``GET /plants/{plant_code}/model-points``
  answer a Viewer, an Engineer and an Admin; an unauthenticated caller 401.
* Every non-GET ``/standards*`` route -- found by walking the application, not
  from a list -- refuses a Viewer with 403. The role check runs before the
  body is read, so nothing is written.
"""

from __future__ import annotations

import pytest
from fastapi.routing import iter_route_contexts

from tests.test_t03_contract import (  # noqa: F401
    admin_client,
    anon_client,
    client,
    engineer_client,
    make_client,
)

pytestmark = pytest.mark.contract

READS = ["/api/v1/standards/catalogue", "/api/v1/plants/AAT/model-points"]


@pytest.mark.parametrize("path", READS)
def test_every_signed_in_role_reads_the_standards(
    client, engineer_client, admin_client, anon_client, path
):
    for reader in (client, engineer_client, admin_client):
        response = reader.get(path)
        assert response.status_code == 200, response.text
    assert anon_client.get(path).status_code == 401


def test_a_viewer_is_refused_every_standards_write(client):
    writes = {
        (method, ctx.path)
        for ctx in iter_route_contexts(client.app.routes)
        if ctx.path.startswith("/api/v1/standards")
        for method in (ctx.methods or set()) - {"GET", "HEAD"}
    }
    assert ("POST", "/api/v1/standards") in writes, sorted(writes)
    assert ("POST", "/api/v1/standards/colours") in writes, sorted(writes)
    for method, path in sorted(writes):
        response = client.request(method, path, json={})
        assert response.status_code == 403, (method, path, response.status_code, response.text)
