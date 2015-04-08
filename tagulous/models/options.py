"""
Tag options
"""

from tagulous import constants
from tagulous.utils import parse_tags, render_tags

PROPERTIES = ['_initial', 'initial_string']


class TagOptions(object):
    """
    Simple class container for tag options
    """
    def __init__(self, **kwargs):
        """
        Set up tag options using defaults, overridden by keyword arguments
        """
        for key, val in kwargs.items():
            setattr(self, key, val)
        
    def __setattr__(self, name, value):
        """
        Only allow an option to be set if it's valid
        """
        if name == 'initial':
            # Store as a list of strings, with the tag string available on
            # initial_string for migrations
            if isinstance(value, basestring):
                self.__dict__['initial_string'] = value
                self.__dict__['initial'] = parse_tags(value)
            else:
                self.__dict__['initial_string'] = render_tags(value)
                self.__dict__['initial'] = value
                
        elif name in constants.OPTION_DEFAULTS:
            self.__dict__[name] = value
        else:
            raise AttributeError(name)
        
    def __getattr__(self, name):
        """
        Get an option, or fall back to default options if it's not set
        """
        if name in PROPERTIES:
            return self.__dict__[name]
        elif name not in constants.OPTION_DEFAULTS:
            raise AttributeError(name)
        return self.__dict__.get(name, constants.OPTION_DEFAULTS[name])
    
    def _get_items(self, with_defaults, keys):
        """
        Return a dict of options specified in keys, with defaults if required
        """
        if with_defaults:
            return dict([
                (name, self.__dict__.get(name, constants.OPTION_DEFAULTS[name]))
                for name in keys
            ])
        
        return dict([
            (name, value) for name, value in self.__dict__.items()
            if name in keys
        ])
    
    def items(self, with_defaults=True):
        """
        Get a dict of all options
        
        If with_defaults is True, any missing options will be set to their
        defaults; if False, missing options will be omitted.
        """
        return self._get_items(with_defaults, constants.OPTION_DEFAULTS)
        
    def field_items(self, with_defaults=True):
        """
        Get a dict of all options in FIELD_OPTIONS, suitable for rendering
        into the data-tag-options attribute of the field HTML.
        
        If with_defaults is True, any missing options will be set to their
        defaults; if False, missing options will be omitted.
        """
        return self._get_items(with_defaults, constants.FIELD_OPTIONS)
        
    def __add__(self, options):
        """
        Return a new TagOptions object with the options set on this object,
        overridden by any on the second specified TagOptions object.
        """
        dct = self.items(with_defaults=False)
        dct.update(options.items(with_defaults=False))
        return TagOptions(**dct)