from django.test import TestCase
from django.contrib.auth.models import User

from .models import Profile


class AccountTestCase(TestCase):
    def setUp(self):
        User.objects.create_superuser('admin', 'admin@fossne.cn', 'admin')
        user = User.objects.create_user('Fossen', 'fossen@fossen.cn', 'fossen')
        Profile.objects.create(user=user, avatar=None, github_id=1,
                               github_url='https://github.com/FossenWang')
        self.client.defaults = {'HTTP_ACCEPT': 'application/json'}

    def test_user(self):
        c = self.client
        # 登录准备
        rsp = c.get('/account/login/prepare/?next=/article/')
        self.assertEqual(rsp.status_code, 200)
        self.assertEqual(rsp.cookies.get('next').value, '/article/')
        csrftoken = rsp.cookies.get('csrftoken').value
        # 模拟登录
        rsp = c.get('/account/oauth/github/?id=2&state=' + csrftoken)
        self.assertEqual(rsp.status_code, 302)
        self.assertEqual(rsp.url, '/article/')
        # 获取用户信息
        rsp = c.get('/account/profile/')
        self.assertEqual(rsp.status_code, 200)
        self.assertEqual(set(rsp.json()), {
            'id', 'github_url', 'avatar', 'new_notice', 'username'})
        self.assertEqual(rsp.json()['id'], 2)
        # 退出登录
        rsp = c.get('/account/logout/')
        self.assertEqual(rsp.status_code, 302)
        # 退出登录后为匿名用户
        rsp = c.get('/account/profile/')
        self.assertEqual(rsp.status_code, 200)
        self.assertEqual(set(rsp.json()), {
            'id', 'github_url', 'avatar', 'new_notice', 'username'})
        self.assertEqual(rsp.json()['id'], None)
