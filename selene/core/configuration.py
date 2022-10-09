# MIT License
#
# Copyright (c) 2015-2022 Iakiv Kramarenko
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import annotations

import atexit
import dataclasses
import itertools
import os
import time
import warnings
from dataclasses import dataclass, field
from typing import Callable, Optional, Union
import re

from selene.common import fp
from selene.common.fp import F

from selene.core.exceptions import TimeoutException
from selenium.webdriver.remote.webdriver import WebDriver

from selene.core.wait import Wait, E


def _strip_underscored_prefix(name: str, prefix='') -> str:
    underscored = f'_{prefix}'
    return name[len(underscored) :] if name.startswith(underscored) else name


def _strip_first_underscore(name: str):
    return _strip_underscored_prefix(name, prefix='')


def _install_and_build_driver(browser_name):
    # todo: do we need here pass self.desired_capabilities too?

    from selenium.webdriver import ChromeOptions, Chrome, Firefox, Edge
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.edge.service import Service as EdgeService
    from selenium.webdriver.firefox.service import Service as FirefoxService
    from webdriver_manager.chrome import ChromeDriverManager
    from webdriver_manager.firefox import GeckoDriverManager
    from webdriver_manager.microsoft import EdgeChromiumDriverManager
    from webdriver_manager.core.utils import ChromeType

    def get_chrome():
        return Chrome(
            service=ChromeService(
                ChromeDriverManager(chrome_type=ChromeType.GOOGLE).install()
            ),
            options=ChromeOptions(),
        )

    def get_firefox():
        return Firefox(service=FirefoxService(GeckoDriverManager().install()))

    def get_edge():
        return Edge(service=EdgeService(EdgeChromiumDriverManager().install()))

    return {
        'chrome': get_chrome,
        'firefox': get_firefox,
        'edge': get_edge,
    }.get(browser_name)()


@dataclass
class _Config:
    timeout: float = 4
    base_url: str = ''

    set_value_by_js: bool = False
    type_by_js: bool = False
    click_by_js: bool = False
    wait_for_no_overlap_found_by_js: bool = False
    log_outer_html_on_failure: bool = False

    window_width: Optional[int] = None
    window_height: Optional[int] = None

    # TODO: better name? now technically it's not a decorator but decorator_builder...
    # or decorator_factory...
    # yet in python they call it just «decorator with args» or «decorator with params»
    # so technically I am correct naming it simply _wait_decorator
    # by type hint end users yet will see the real signature
    # and hence guess its «builder-like» nature
    # yet... should we for verbosity distinguish options
    # that a decorator factories from options that are simple decorators?
    # maybe better time to decide on this will be once we have more such options :p
    _wait_decorator: Callable[
        [Wait[E]], Callable[[F], F]
    ] = lambda _: fp.identity

    hook_wait_failure: Optional[Callable[[TimeoutException], Exception]] = None
    '''
    A handler for all exceptions, thrown on failed waiting for timeout.
    Should process the original exception and rethrow it or the modified one. 
    
    TODO: why we name it as hook_* why not handle_* ?
          what would be proper style?
    '''

    # -- from SharedConfig --

    # TODO: consider accepting also hub url as "browser"
    #       because in case of "remote" mode, we will not need the common "name" like
    #       chrome or ff
    #       but we would pass the same name somewhere in caps... to choose correct "platform"
    #       so... then browser_name is kind of incorrect name becomes...
    #       why then not rename browser_name here to just browser...
    #       then... technically it might be possible to write something like:
    #           browser.config.browser = ... :)
    #              how can we make it impossible?
    #              or what else better name can we choose?
    #       ...
    #       if we are going to accept config.options
    #       where best it would be to put remote_url?
    #       config.service? config.driver? config.remote_url? config.executor?
    browser_name: str = 'chrome'
    """
    desired name of the browser
    """
    hold_browser_open: bool = False
    poll_during_waits: int = 100
    """
    a fake option, not currently used in Selene waiting:)
    """
    save_screenshot_on_failure: bool = True
    save_page_source_on_failure: bool = True
    # counter: itertools.count = dataclasses.field(
    #     default_factory=lambda: itertools.count(
    #         start=int(round(time.time() * 1000))
    #     )
    # )
    # """
    # screenshots counter
    # """
    reports_folder: str = ...

    driver: Union[WebDriver, Callable[[], WebDriver]] = ...
    _driver: WebDriver = field(default=..., init=False, repr=False)
    _driver_source: Callable[[], WebDriver] = field(
        default=..., init=False, repr=False
    )

    def _get_driver(self) -> WebDriver:  # noqa
        """
        a driver property getter; set after class definition explicitly, below...
        """
        self._driver = self._driver_source()
        return self._driver

    def get_or_create_driver(self) -> WebDriver:
        warnings.warn(
            'config.get_or_create_driver is deprecated, use config.driver instead',
            DeprecationWarning,
        )
        return self.driver

    def _set_driver(self, value: Union[WebDriver, Callable[[], WebDriver]]):
        """
        a driver property setter; set after class definition explicitly, below...
        """

        def ensure_installed_and_built_when_not_alive():
            return (
                self._driver
                if (self._driver is not ... and self.is_browser_alive)
                else _install_and_build_driver(self.browser_name)
            )

        if (
            # driver was previously set via built-in driver-management logic
            re.sub(' at 0x.+>$', '>', str(self._driver_source))
            == re.sub(
                ' at 0x.+>$',
                '>',
                str(ensure_installed_and_built_when_not_alive),
            )
            # and ...
            and self._driver is not ...
            and self.is_browser_alive
        ):
            self._driver.quit()

        if value is ... or value is None:
            self._driver = ...
            self._driver_source = ensure_installed_and_built_when_not_alive
        elif callable(value):
            self._driver = ...
            self._driver_source = value
        else:
            self._driver = value
            self._driver_source = lambda: value

        atexit.register(
            lambda: (
                self.driver.quit()
                if not self.hold_browser_open
                and self._driver is not ...
                and self.is_browser_alive
                else None
            )
        )

    def _reset_driver_source(self):
        """
        set default value (...) to the self.driver and so to the self._driver
        Hence, by this – also resetting self._driver_source,
        i.e. returning its original «automatically managed by Selene» version

        TODO: should we make this method public?
              currently the official way to reset driver source for the user
              is `browser.config.driver = ...`
              wouldn't it be better to allow him to do:
              is `browser.config.reset_driver_source()`
              ?
        """
        self.driver = ...

    def reset_driver(self):  # noqa
        warnings.warn(
            'selene.browser.config.reset_driver is deprecated '
            'in favor of `config.driver = ...`',
            DeprecationWarning,
        )
        self.driver = ...

    @property
    def is_browser_alive(self) -> bool:
        if self._driver is ...:
            # raise _SeleneError('the driver has not been sourced yet at config')
            warnings.warn(
                'The driver has not been sourced yet at config, '
                'but asked for being alive. '
                'There might be a situation when driver is already created '
                'and so alive but passed to config via callable '
                'and not sourced yet at config...'
            )
            return False

        try:
            return self._driver.title is not None
        except Exception:  # noqa
            return False

    def __post_init__(self):
        self._counter = itertools.count(start=int(round(time.time() * 1000)))
        if self.reports_folder is ...:
            self.reports_folder = os.path.join(
                os.path.expanduser('~'),
                '.selene',
                'screenshots',
                str(next(self._counter)),
            )
        # TODO: consider making private
        self.last_screenshot: Optional[str] = None
        self.last_page_source: Optional[str] = None

    def as_dict(self):
        return dict(
            (field.name, getattr(self, field.name))
            for field in dataclasses.fields(self)  # noqa
        )

    def with_(self, **config_as_kwargs) -> _Config:
        return dataclasses.replace(self, **config_as_kwargs)

    def _inject_screenshot_and_page_source_pre_hooks(self, hook):
        # todo: consider moving hooks to class methods accepting config as argument
        #       or refactor somehow to eliminate all times defining hook fns
        def save_and_log_screenshot(error: TimeoutException) -> Exception:
            from selene.support.webdriver import WebHelper

            path = WebHelper(self.driver).save_screenshot(
                self._generate_filename(suffix='.png')
            )
            self.last_screenshot = path
            return TimeoutException(
                error.msg
                + f'''
Screenshot: file://{path}'''
            )

        def save_and_log_page_source(error: TimeoutException) -> Exception:
            filename = (
                self.last_screenshot.replace('.png', '.html')
                if self.last_screenshot
                else self._generate_filename(suffix='.html')
            )
            from selene.support.webdriver import WebHelper

            path = WebHelper(self.driver).save_page_source(filename)
            self.last_page_source = path
            return TimeoutException(
                error.msg
                + f'''
PageSource: file://{path}'''
            )

        return fp.pipe(
            save_and_log_screenshot
            if self.save_screenshot_on_failure
            else None,
            save_and_log_page_source
            if self.save_page_source_on_failure
            else None,
            hook,
        )

    # TODO: do we really need it here?
    def wait(self, entity):
        hook = self._inject_screenshot_and_page_source_pre_hooks(
            self.hook_wait_failure
        )
        return Wait(
            entity,
            at_most=self.timeout,
            or_fail_with=hook,
            _decorator=self._wait_decorator,
        )

    def _generate_filename(self, prefix='', suffix=''):
        warnings.warn('', DeprecationWarning)
        path = self.reports_folder
        next_id = next(self._counter)
        filename = f'{prefix}{next_id}{suffix}'
        file = os.path.join(path, f'{filename}')

        folder = os.path.dirname(file)
        if not os.path.exists(folder) and folder:
            os.makedirs(folder)

        return file


_Config.driver = property(_Config._get_driver, _Config._set_driver)  # noqa
'''
a hack to make _Config.driver to work as property with custom getter and setter
TODO: consider using field_property from https://github.com/wyfo/field-properties
      or consider using property_wizard metaclass
      from https://dataclass-wizard.readthedocs.io/en/latest/using_field_properties.html
'''


class Config(_Config):
    ...
