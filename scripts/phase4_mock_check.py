"""真实语料检索→提示词→Mock HTTP→引用核验；此脚本绝无真实HTTP传输。"""
from pathlib import Path
import json
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.config import Settings
from src.corpus import load_corpus
from src.deepseek_client import DeepSeekClient
from src.qa import AnswerEngine
from src.retriever import Retriever


class MockTransport:
    def __init__(self):
        self.calls=0

    def post(self,url,*,headers,json,timeout,allow_redirects=False):
        self.calls+=1
        assert url=='https://api.deepseek.com/chat/completions' and not allow_redirects
        assert '课件证据' in json['messages'][1]['content']
        class Response:
            status_code=200
            @staticmethod
            def json():
                return {'choices':[{'message':{'content':'2）控制系统失灵；现代工程：高度复杂、高度集成，但智能程度不高，存在引发事故的隐患。 [S1]'},'finish_reason':'stop'}],
                        'usage':{'prompt_tokens':400,'completion_tokens':70,'total_tokens':470}}
        return Response()


def main():
    (ROOT/'.pytest_tmp').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='phase4-mock-',dir=ROOT/'.pytest_tmp') as temporary:
        settings=Settings(deepseek_api_key='mock-credential-not-real',api_enabled=True,api_state_path=Path(temporary)/'limit.sqlite3')
        transport=MockTransport()
        client=DeepSeekClient(settings,session=transport)
        engine=AnswerEngine(Retriever(load_corpus()),settings=settings,client=client)
        result=engine.answer('工程风险的技术因素有哪些？',provider='deepseek',allow_api=True)
        assert result.provider=='deepseek' and transport.calls==1
        output={'is_mock':True,'real_http_requests':0,'mock_http_requests':transport.calls,'real_cost':0,
                'usage_note':'以下token数为Mock固定测试值，不是实际计费数据',
                'status':result.status,'provider':result.provider,'model':result.model,'answer':result.answer,
                'citations':[dict(filename=h.page.filename,page_number=h.page.page_number,quality=h.review_label) for h in result.citations],
                'mock_usage':result.usage,'request_attempts_in_mock_ledger':client.limiter.used()}
        target=ROOT/'reports/phase4_integration/mock_result.json'
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Mock联调通过：真实语料检索、Mock HTTP 1次、真实HTTP 0次。')


if __name__=='__main__':main()
