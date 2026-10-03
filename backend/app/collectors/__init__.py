from .surface.github import GitHubCollector
from .surface.gitlab import GitLabCollector
from .surface.reddit import RedditCollector
from .surface.web import WebCollector
from .onion.collector import OnionCollector


COLLECTORS = {
    "github": GitHubCollector(),
    "gitlab": GitLabCollector(),
    "reddit": RedditCollector(),
    "web": WebCollector(),
    "onion": OnionCollector(),
}