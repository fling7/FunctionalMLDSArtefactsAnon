"""Regression only: packet goldens are not an independent oracle."""
import json
from pathlib import Path
import pytest
from experiments.lib.backend_driver import Driver,ROOT
BASELINE=json.loads((ROOT/'results/raw/packet_regression.json').read_text())
@pytest.fixture(scope='module')
def driver():
    d=Driver()
    yield d
    d.close()
@pytest.mark.parametrize('row',BASELINE['probes'],ids=lambda r: r['agent']+'-'+r['target']+'-'+r['variant'])
def test_packet_decisions_preserved(driver,row):
    target=next(t for t in driver.targets if t['id']==row['target'])
    actual=driver.probe(driver.request(row['agent'],target,row['variant']))
    for key in ['decision','provider','action','model_calls']:
        assert actual[key]==row[key]
    if actual['decision']=='REJECT':
        assert actual['unchanged_before_restore']
        assert actual['model_calls']==0
