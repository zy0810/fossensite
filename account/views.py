import requests

from django.shortcuts import redirect, reverse
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist
from django.views.generic import FormView, TemplateView
from django.contrib.auth.models import User
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Q
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator

from fossensite import settings
from comment.models import ArticleComment, ArticleCommentReply
from tools.views import JSONView, ListView
from tools.base import update_model

from .models import Profile, BlankProfile
from .forms import OauthEditUsernameForm


class UserHomeView(LoginRequiredMixin, ListView):
    '用户主页'
    model = ArticleCommentReply
    template_name = 'account/user_home.html'
    context_object_name = 'notices'
    paginate_by = 10

    def get_queryset(self):
        uid = self.request.user.id
        self.request.user.profile.have_read_notice()
        return super().get_queryset() \
            .filter(Q(comment__user_id=uid) | Q(reply__user_id=uid)) \
            .exclude(user=uid).order_by('-time') \
            .select_related('user', 'user__profile', 'comment__article') \
            .only('content', 'time', 'user__username', 'user__profile__avatar', 'comment__article__title')


class CommentNoticesView(UserPassesTestMixin, ListView):
    '文章评论通知'
    model = ArticleComment
    template_name = 'account/comment_notices.html'
    context_object_name = 'notices'
    paginate_by = 10
    raise_exception = True

    def test_func(self):
        if self.request.user.id != 2:
            return False
        else:
            return True

    def get_queryset(self):
        self.request.user.profile.have_read_notice()
        return super().get_queryset() \
            .select_related('user', 'user__profile', 'article') \
            .only('content', 'time', 'user__username', 'user__profile__avatar', 'article__title')


class ProfileDetailView(JSONView):
    '登录用户的资料视图'

    def get(self, request):
        user = request.user
        try:
            profile = user.profile
        except (ObjectDoesNotExist, AttributeError):
            profile = BlankProfile
        data = {
            'id': user.id,
            'username': user.username,
            'avatar': profile.avatar.name if profile.avatar else None,
            'github_url': profile.github_url,
            'new_notice': profile.new_notice,
        }
        return data


@method_decorator(ensure_csrf_cookie, name='dispatch')
class PrepareLoginView(JSONView):
    '第三方登录视图'
    template_name = 'account/login.html'

    def get(self, request, **kwargs):
        context = {'github_oauth_url': 'https://github.com/login/oauth/authorize?client_id={}&state={}' \
            .format(settings.GITHUB_CLIENT_ID, self.request.META['CSRF_COOKIE'])}
        rsp = self.render_to_json_response(context)
        next_url = self.request.GET.get('next')
        if next_url:
            rsp.set_cookie('next', next_url)
        return rsp


class GitHubOAuthView(JSONView):
    'github账号认证视图'
    access_token_url = settings.GITHUB_ACCESS_TOKEN_URL
    user_api = settings.GITHUB_USER_API
    client_id = settings.GITHUB_CLIENT_ID
    client_secret = settings.GITHUB_CLIENT_SECRET

    def get(self, request, *args, **kwargs):
        if settings.DEBUG and self.request.GET.get('id'):
            return self.login_in_test()
        access_token = self.get_access_token()
        user_info = self.get_user_info(access_token)
        return self.authenticate(user_info)

    def get_access_token(self):
        '获取access token'
        if self.request.GET.get('state') != self.request.COOKIES.get('csrftoken'):
            raise PermissionDenied()

        url = self.access_token_url
        headers = {'Accept': 'application/json'}
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'code': self.request.GET.get('code')
        }
        r = requests.post(url, data, headers=headers, timeout=3)
        result = r.json()
        if 'access_token' not in result:
            raise PermissionDenied()
        return result['access_token']

    def get_user_info(self, access_token):
        '获取用户信息'
        url = self.user_api + access_token
        r = requests.get(url, timeout=3)
        user_info = r.json()
        return user_info

    def authenticate(self, user_info):
        user = User.objects.filter(profile__github_id=user_info.get('id'))
        if not user:
            if User.objects.filter(username=user_info.get('login')).exists():
                # 若用户名已存在，则需要改名
                self.request.session['github_oauth'] = user_info
                return redirect(reverse('account:edit_name'))

            user = User.objects.create_user(user_info.get('login'))
            profile = Profile(user=user, avatar=user_info.get('avatar_url'),
                              github_id=user_info.get('id'),
                              github_url=user_info.get('html_url'))
            profile.save()
        else:
            update_model(user.profile, {'avatar': user_info.get('avatar_url'),
                                        'github_url': user_info.get('html_url')})
            user = user[0]
        return self.login_user(user)

    def login_user(self, user):
        login(self.request, user)

        url = self.request.COOKIES.get('next')
        if not url:
            url = '/'
        rsp = redirect(url)
        rsp.delete_cookie('next')
        return rsp

    def login_in_test(self):
        if self.request.GET.get('state') != self.request.COOKIES.get('csrftoken'):
            raise PermissionDenied('Wrong csrftoken.')
        try:
            user = User.objects.get(pk=self.request.GET.get('id'))
        except ObjectDoesNotExist:
            raise PermissionDenied('没有该用户')
        return self.login_user(user)


class OAuthEditUsername(FormView):
    '通过第三方账户注册时，用户名若重复，则通过该视图修改合适的用户名'
    template_name = 'account/edit_name.html'
    form_class = OauthEditUsernameForm

    def dispatch(self, request, *args, **kwargs):
        if 'github_oauth' not in request.session:
            raise PermissionDenied('未经GitHub验证')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['username'] = self.request.session['github_oauth']['login']
        return context

    def form_valid(self, form):
        """If the form is valid, save the associated model."""
        if 'github_oauth' in self.request.session:
            user_info = self.request.session.pop('github_oauth')
            user = form.save()
            profile = Profile(
                user=user, github_id=user_info.get('id'), avatar=user_info.get('avatar_url'))
            profile.save()
            login(self.request, user)
        return super().form_valid(form)

    def get_success_url(self):
        url = self.request.COOKIES.get('next')
        if not url:
            url = '/'
        return url
