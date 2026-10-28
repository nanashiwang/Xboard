import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('rotation',Path(__file__).resolve().parents[2]/'.docker/dedicated/rotate-us.py')
rotation=importlib.util.module_from_spec(spec)
spec.loader.exec_module(rotation)


class SubscriptionNamesTest(unittest.TestCase):
    def test_production_protocol_prefix_and_information_rows(self):
        names=['剩余流量：1024 MB','距离下次重置剩余：1 天','套餐到期：2026-10-28',
               '美国02｜2×｜家宽','美国01｜2×｜家宽','香港01｜1×','日本01｜1×','荷兰01｜1×','罗马尼亚01｜1×']
        config={'outbounds':[{'type':'selector','tag':'选择节点'}]+[{'type':'vless','tag':'[vless]'+name} for name in names]}
        self.assertEqual(names[3:],rotation.subscription_names(config))

    def test_unexpected_routes_and_duplicates_remain_visible_to_scope_checks(self):
        names=['美国01｜2×｜家宽','美国01｜2×｜家宽','美国10｜2×｜家宽','旧美国出口']
        config={'outbounds':[{'type':'vless','tag':name} for name in names]}
        self.assertEqual(names,rotation.subscription_names(config))


if __name__=='__main__':unittest.main()
