"""Classes to parse and encapsulate node parameter description."""

import re
from collections import OrderedDict
import rman_utils.logger as default_logger


default_logger.setup('rman')
__log__ = default_logger.rman_log()


def set_logger(obj):
    """Set the logger for all module functions."""
    global __log__      # pylint: disable=global-statement
    __log__ = obj


def logger():
    """Return the current logging.logger object."""
    return __log__


def to_bool(val):
    """force conversion to bool."""
    try:
        return bool(int(val))
    except ValueError:
        try:
            return bool(val)
        except ValueError:
            if val in ('true', 'false'):
                return bool(val.capitalize())
    raise ValueError('Failed to convert: %r' % val)



VALID_TYPES = ['int', 'int2', 'float', 'float2', 'color', 'point', 'vector',
               'normal', 'matrix', 'string', 'struct', 'lightfilter',
               'message', 'displayfilter', 'samplefilter', 'bxdf']
FLOAT3 = ['color', 'point', 'vector', 'normal']
FLOATX = ['color', 'point', 'vector', 'normal', 'matrix']
DATA_TYPE_WIDTH = {'int': 1, 'float': 1,
                   'color': 3, 'point': 3, 'vector': 3, 'normal': 3,
                   'matrix': 16, 'string': 0, 'struct': 0}
DEFAULT_VALUE = {'float': 0.0, 'float2': (0.0, 0.0), 'float3': (0.0, 0.0, 0.0),
                 'int': 0, 'int2': (0, 0),
                 'color': (0.0, 0.0, 0.0), 'normal': (0.0, 0.0, 0.0),
                 'vector': (0.0, 0.0, 0.0), 'point': (0.0, 0.0, 0.0),
                 'string': '',
                 'matrix': (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                            0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0),
                 'message': None}
CFLOAT_REGEXP = re.compile(r'[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?f').match
PAGE_SEP = '|'
REPR_FMT = '%s object at %s (name: %s)'
RE_VISOP = re.compile(r'.+(Left|Right|Op|Path|Value)$')


class NodeDescError(Exception):
    """Custom exception for NodeDesc-related errors."""

    def __init__(self, value):
        super(NodeDescError, self).__init__(value)
        self.value = 'NodeDesc Error: %s' % value

    def __str__(self):
        return str(self.value)


def osl_metadatum(metadict, name, default=None):
    """Return metadatum value, based on oslquery's return format."""
    if name in metadict:
        return metadict[name]['default']
    else:
        return default


def safe_value_eval(raw_val):
    """Evaluate a string to a value, taking care of identifying data type."""
    val = raw_val
    try:
        val = eval(raw_val)     # pylint: disable = eval-used
    except BaseException:
        val = raw_val
    else:
        if isinstance(val, type):
            # catch case where 'int' (or any other python type)
            # was evaled and we got a python type object.
            val = raw_val
    return val


def validate_type(pname, ptype):
    """Raise a NodeDescError if ptype is not a known data type."""
    if ptype in VALID_TYPES:
        return ptype
    raise NodeDescError('param %r has invalid type: %r' % (pname, ptype))


class DescPropType(object):
    """Encodes the type of property.

    Attributes:
        Attribute (str): RIB attribute attached to the node
        Output (str): Output parameter
        Param (str): Input parameter
    """
    # pylint: disable=invalid-name
    Param = 'param'
    Output = 'output'
    Attribute = 'attr'


class NodeDescParam(object):
    """A base class for parameter descriptions. It has only 2 mandatory attributes:
    name and type. Defaults, array and ui configuration attributes are all
    optional.

    Attributes:
        name (str): the parameter's name
        type (TYPE): the parameter's data type
    """
    # pylint: disable=attribute-defined-outside-init

    optional_attrs = [
        'URL', 'buttonText', ('connectable', to_bool), 'digits', 'label', 'match', 'max',
        'min', 'riattr', 'riopt', 'scriptText', 'sensitivity', 'slider',
        'slidermax', 'slidermin', 'syntax', 'tag', 'units', 'vstructConditionalExpr',
        'vstructmember', ('hidden', to_bool), ('color_enableFilmlookVis', to_bool),
        ('readOnly', to_bool), ('editable', to_bool), ('lockgeom', to_bool)]

    def __init__(self, build_condvis_func):
        self._name = None
        self.type = None
        self.default = None
        self.has_ui_struct = False
        self.conditionalVisOps = {}             # pylint: disable=invalid-name
        self.trigger_params = []
        self.conditionalVisTrigger = False      # pylint: disable=invalid-name
        self.build_condvis_func = build_condvis_func

    @property
    def name(self):
        """Returns the parameter's name."""
        return self._name

    @name.setter
    def name(self, value):
        """Sets the parameter's name. If overriden, allows to sanity-check the
        new name or pre-configure other aspects of the object."""
        self._name = value

    def get_help(self):
        """Returns the help string or a minimal parameter description (type and
        name) if not available.
        NOTE: the help string may have been re-formated during description
        parsing.

        Returns:
            str: The help string.
        """
        return getattr(self, 'help', '%s %s' % (self.type, self.name))

    def is_array(self):
        """True if this is an array parameter."""
        # pylint: disable=no-member
        return self.size is not None

    def finalize(self):
        """Post-process the description data:
        - make some attribute types non-connectable (int, matrix)
        - escapes some characters for maya consumption.
        - processes conditional visibility.

        Returns:
            None
        """
        if self.default is None:
            self.default = DEFAULT_VALUE.get(self.type, None)

        if self.type in ['float', 'int']:
            if hasattr(self, 'min'):
                # set a slidermax if not defined.
                if not hasattr(self, 'max') and not hasattr(self, 'slidermax'):
                    setattr(self, 'slidermax', max(self.default, 1.0))
            elif hasattr(self, 'slider'):
                # set a 0->1 soft limit if none defined.
                if not hasattr(self, 'min') and not hasattr(self, 'slidermin'):
                    setattr(self, 'slidermin', min(self.default, 0.0))
                if not hasattr(self, 'max') and not hasattr(self, 'slidermax'):
                    setattr(self, 'slidermax', max(self.default, 1.0))

        # Parse conditional visibility
        if self.conditionalVisOps and self.build_condvis_func is not None:
            self.build_condvis_func(self.conditionalVisOps, self.trigger_params)

    def condvis_trigger_params(self):
        """Returns a list of parameters triggering conditional visibility
        evaluation."""
        return self.trigger_params

    def condvis_set_trigger(self, state):
        """Mark this parameter as a conditional visibility trigger."""
        self.conditionalVisTrigger = state

    def condvis_get_trigger(self):
        """True if this parameter triggers conditional visibility evaluation."""
        return self.conditionalVisTrigger

    def _format_help(self):
        # pylint: disable=no-member
        if hasattr(self, 'help') and self.help is not None:
            attr_type_str = '%s (%s)' % (self.name, self.type)
            if not self.help.endswith(attr_type_str):
                if self.help:
                    self.help += '<br><br>'
                self.help += attr_type_str

    def as_dict(self):
        """Return the param attributes as a sorted ordered dict."""
        obj_vars = dict(vars(self))
        if '_name' in obj_vars:
            obj_vars['name'] = obj_vars['_name']
            del obj_vars['_name']
        out_dict = OrderedDict()
        for var in sorted(obj_vars):
            out_dict[var] = obj_vars[var]
        return out_dict

    def __str__(self):
        """Encodes the data in a human-readable form.
        Used for serialisation.

        Returns:
            str: A human-friendly version of the object's contents.
        """
        fos = 'Param: %s\n' % self.name
        dct = vars(self)
        for key, val in sorted(dct.items()):
            if isinstance(val, float):
                fos += '  | %s: %g\n' % (key, val)
            else:
                fos += '  | %s: %s\n' % (key, repr(val))
        return fos

    def __repr__(self):
        return REPR_FMT % (self.__class__, hex(id(self)), self.name)


class NodeDescParamXML(NodeDescParam):
    """Specialization for XML/args syntax"""
    # pylint: disable=attribute-defined-outside-init


    def __init__(self, pdata, build_condvis_func=None):
        """Parse the xml data and store it.

        Args:
            pdata (xml): A xml element.
            build_condvis_func (obj): A functions that can return a conditional
                                      visibility expression taylored for a specific
                                      host/DCC.
        """
        super(NodeDescParamXML, self).__init__(build_condvis_func)
        self.name = pdata.getAttribute('name')
        self.type = validate_type(self.name, self._set_type(pdata))
        self._set_optional_attributes(pdata)
        self.finalize()

    def _set_type(self, pdata):
        """Sets the data type of the parameter. It may return None if the type
        could not be found.

        Args:
            pdata (xml): A xml element.

        Returns:
            str: The data type ('float', 'color', etc)
        """
        if pdata.hasAttribute('type'):
            return pdata.getAttribute('type')
        else:
            tags = pdata.getElementsByTagName('tags')
            if tags:
                tag = tags[0].getElementsByTagName('tag')
                for itg in tag:
                    if itg.hasAttribute('value'):
                        return itg.getAttribute('value')
            else:
                # some args files have something like:
                # <output name="outColor" tag="color|vector|normal|point"/>
                tag = pdata.getAttribute('tag')
                if tag:
                    tags = tag.split('|')
                    if tags:
                        for itg in tags:
                            return itg
        return None

    def _set_size(self, pdata):
        """Sets the attribute size:
        * None: this is a simple non-array attribute.
        * -1: this is a dynamic array.
        * [0-9]+: this is a fixed size array.

        Args:
            pdata (cml): A xml element

        Returns:
            int or None: The size of the array.
        """
        if pdata.hasAttribute('isDynamicArray'):
                # dynamic array
            if pdata.getAttribute('isDynamicArray') != '0':
                self.size = - 1
            elif pdata.hasAttribute('arraySize'):
                self.size = int(pdata.getAttribute('arraySize'))
        elif pdata.hasAttribute('arraySize'):
            # fixed-size array
            self.size = int(pdata.getAttribute('arraySize'))
        else:
            # non-array
            self.size = None

    def _set_default(self, pdata):
        """Store default value(s).

        Array storage format is as follow:
        float: [v0, v1, ...]
        float3: [(v0, v1, v2), ...]
        matrices: [(v0, v1, ..., v15), ...]

        Args:
            pdata (xml): xml element

        Returns:
            any: a list, list of tuples or single variable
        """
        if not pdata.hasAttribute('default'):
            return
        if self.type == 'struct':
            self.default = ""
            return
        pdefault = pdata.getAttribute('default')
        pdefault = self._handle_c_style_floats(pdefault)
        if 'string' not in self.type:
            psize = getattr(self, 'size', None)
            if psize is None:
                # non-array numerical values
                self.default = safe_value_eval(pdefault.replace(' ', ','))
            else:
                # arrays
                vals = pdefault.split()
                str_to_num = float
                if self.type == 'int':
                    str_to_num = int
                twidth = DATA_TYPE_WIDTH[self.type]
                self.default = []
                if twidth > 1:
                    for i in range(0, len(vals), twidth):
                        tvals = []
                        for j in range(twidth):
                            tvals.append(str_to_num(vals[i + j]))
                        self.default.append(tuple(tvals))
                else:
                    for val in vals:
                        self.default.append(str_to_num(val))
                # conform defaults to array size
                if len(self.default) == 1 and psize > 0:
                    self.default = self.default * psize
        else:
            # strings: there is no provision for string array defaults
            # in katana.
            self.default = pdefault

    def _set_page(self, pdata):
        """Store the page path for this param.
        The page will be stored as a path: specular/Advanced/Anisotropy

        Args:
            pdata (xml): xml element
        """
        self.page = ''
        p_node = pdata.parentNode
        # consider the open state only for the innermost page.
        if p_node.hasAttribute('open'):
            self.page_open = (
                str(p_node.getAttribute('open')).lower() == 'true')
        # go up the page hierarchy to build the full path to this page.
        while p_node.tagName == 'page':
            self.page = p_node.getAttribute('name') + PAGE_SEP + self.page
            p_node = p_node.parentNode
        if self.page[-1:] == PAGE_SEP:
            self.page = self.page[:-1]

    def _set_help(self, pdata):
        has_help = True
        help_node = pdata.getElementsByTagName('help')
        if help_node:
            self.help = help_node[0].firstChild.data
        elif pdata.hasAttribute('help'):
            self.help = pdata.getAttribute('help')
        else:
            has_help = False
        if has_help:
            self.help = re.sub(r'\n\s+', '<br>', self.help.strip())
        self._format_help()

    def _set_widget(self, pdata):

        # support popup options defined as:
        #   options="first option|second option|third option"
        # as well as dicts:
        #   options="one:1|two:2|three:3"
        if pdata.hasAttribute('options'):
            tmp = pdata.getAttribute('options')
            self.options = OrderedDict()
            if ':' in tmp:
                for tok in tmp.split('|'):
                    kval = tok.rsplit(':', 1)
                    try:
                        self.options[kval[0]] = kval[1]
                    except ValueError:
                        self.options[kval[0]] = kval[0]
            elif '|' in tmp:
                for opt in tmp.split('|'):
                    self.options[opt] = opt
            else:
                self.options[tmp] = tmp

        # or as hintlist:
        # # <hintlist name = "options" >
        #     <string value="0.0"/>
        #     <string value="0.5"/>
        # </hintlist>
        # NOTE: in the example above, the result will be:
        #   self.options = ['0.0', '0.5']
        # because the list members are defined as 'string' values.
        hintlist = pdata.getElementsByTagName('hintlist')
        for hint in hintlist:
            hname = hint.getAttribute('name')
            elmts = hint.getElementsByTagName('*')
            val_dict = OrderedDict()
            for elmt in elmts:
                etype = elmt.tagName
                raw_val = elmt.getAttribute('value')
                val = raw_val
                if etype in FLOATX:
                    val = tuple([float(v) for v in raw_val.split()])
                elif etype != 'string':
                    val = safe_value_eval(raw_val)
                val_dict[val] = val
            setattr(self, hname, val_dict)

        # hintdict is a special case because it is not a simple attribute.
        # support multiple hintdicts and store them under their name.
        # This includes 'options', 'conditionalVisOps', etc
        hintdict = pdata.getElementsByTagName('hintdict')
        for hint in hintdict:
            dict_name = hint.getAttribute('name')
            setattr(self, dict_name, OrderedDict())
            elmts = hint.getElementsByTagName('*')
            this_attr = getattr(self, dict_name)
            for elmt in elmts:
                elmt_type = elmt.tagName
                key = elmt.getAttribute('name')
                raw_val = elmt.getAttribute('value')
                val = raw_val
                if elmt_type in FLOATX:
                    val = tuple([float(v) for v in raw_val.split()])
                else:
                    val = safe_value_eval(val)
                this_attr[key] = val

        if pdata.hasAttribute('widget'):
            self.widget = pdata.getAttribute('widget')
        else:
            self.widget = 'default'

    def _set_conditional_vis_ops(self, pdata):
        # gather conditional visibility ops
        for i in range(pdata.attributes.length):
            pname = pdata.attributes.item(i).name
            if re.match(RE_VISOP, pname):
                val = pdata.getAttribute(pname)
                if '/' in val:
                    val = val.rsplit('/', 1)[-1]
                self.conditionalVisOps[pname] = safe_value_eval(val)

    def _set_optional_attributes(self, pdata):
        self._set_size(pdata)
        self._set_default(pdata)
        self._set_widget(pdata)
        self._set_page(pdata)
        self._set_help(pdata)
        self._set_conditional_vis_ops(pdata)

        # optional attributes
        for attr in self.optional_attrs:
            func = None
            if isinstance(attr, tuple):
                attr, func = attr
            if pdata.hasAttribute(attr):
                val = pdata.getAttribute(attr)
                val = self._handle_c_style_floats(val)
                if self.type in FLOAT3 and self.size is None:
                    if 'min' in attr or 'max' in attr:  # 'min' or 'slidermin'
                        val = tuple([float(v) for v in val.split()])
                try:
                    val = safe_value_eval(val)
                except BaseException:
                    pass
                setattr(self, attr, val if not func else func(val))

        # check if float param used as vstruct port
        tags = pdata.getElementsByTagName('tags')
        if len(tags):
            elmts = tags[0].getElementsByTagName('*')
            for elmt in elmts:
                if elmt.hasAttribute('value'):
                    if elmt.getAttribute('value') == 'vstruct':
                        self.vstruct = True
                        break

        # widget sanity check
        # Katana doesn't support widget variants (e.g. int->checkBox) for array
        # attributes, so we will set the widget to "default" instead of
        # dynamicArray.
        if hasattr(self, 'widget'):
            # there is no garantee a widget attribute exists.
            if self.widget == 'dynamicArray':
                self.widget = 'default'

    def __repr__(self):
        return REPR_FMT % (self.__class__, hex(id(self)), self.name)

    def _handle_c_style_floats(self, val):
        """
        Make sure a float value from an args file doesn't contain a 'f',
        like in '0.001f'.
        """
        if CFLOAT_REGEXP(str(val)):
            return val.replace('f', '')
        else:
            return val


class NodeDescParamOSL(NodeDescParam):
    """Specialization for OSL syntax"""

    # pylint: disable=attribute-defined-outside-init

    def __init__(self, pdata, build_condvis_func=None):
        super(NodeDescParamOSL, self).__init__(build_condvis_func)
        metadict = {d['name']: d for d in pdata['metadata']}
        self.category = self._set_category(pdata)
        self.name = self._set_name(pdata)
        self.type = validate_type(self.name, self._set_type(pdata))
        self._set_optional_attributes(pdata, metadict)
        self.finalize()

    def _set_category(self, pdata):
        # NOTE: can we support attributes in OSL metadata ?
        if pdata['isoutput']:
            # this is a struct parameter
            return DescPropType.Output
        else:
            return DescPropType.Param

    def _set_name(self, pdata):
        return pdata['name']

    def _set_type(self, pdata):
        if pdata['isstruct']:
            self.struct_name = pdata['structname']
            return 'struct'
        return pdata['type'].split('[')[0]

    def _set_size(self, pdata):
        if pdata['varlenarray']:
            self.size = -1
        elif pdata['arraylen'] > 0:
            self.size = pdata['arraylen']
        else:
            self.size = None

    def _set_default(self, pdata):
        self.default = pdata['default']

    def _set_page(self, metadict):
        if 'page' in metadict:
            self.page = osl_metadatum(metadict, 'page', None).replace('.', PAGE_SEP)
            # the page's open state at startup in OSL.
            # Should be set on the first param of the page.
            self.page_open = osl_metadatum(metadict, 'page_open', False)

    def _set_help(self, metadict):
        self.help = osl_metadatum(metadict, 'help', '').replace('  ', ' ')
        self._format_help()

    def _set_widget(self, metadict):
        # hintdict
        if 'options' in metadict:
            self.options = OrderedDict()
            olist = osl_metadatum(metadict, 'options').split('|')
            key = None
            val = None
            for opt in olist:
                if ':' in opt:
                    key, val = opt.rsplit(':', 1)  # consider only first ':'
                else:
                    key = opt
                    val = opt
                try:
                    self.options[key] = safe_value_eval(val)
                except BaseException:
                    self.options[key] = val

        if 'presets' in metadict:
            self.presets = OrderedDict()
            plist = osl_metadatum(metadict, 'presets').split('|')
            for preset in plist:
                key, val = preset.split(':')
                if self.type in FLOATX:
                    self.presets[key] = tuple([float(v) for v in val.split()])
                elif self.type == 'string':
                    self.presets[key] = val
                else:
                    self.presets[key] = safe_value_eval(val)

        self.widget = osl_metadatum(metadict, 'widget', 'default')

    def _set_conditional_vis_ops(self, metadict):
        # build conditional vis ops
        for key, val in metadict.items():
            if re.match(RE_VISOP, key):
                self.conditionalVisOps[key] = safe_value_eval(val['default'])

    def _set_optional_attributes(self, pdata, metadict):
        self._set_size(pdata)
        self._set_default(pdata)
        self._set_widget(metadict)
        self._set_page(metadict)
        self._set_help(metadict)
        self._set_conditional_vis_ops(metadict)

        def __set_attr_named(attr_name):
            func = None
            if isinstance(attr_name, tuple):
                attr_name, func = attr_name
            if attr_name not in metadict:
                return
            val = metadict[attr_name]['default']
            # val = safe_value_eval(val)
            setattr(self, attr_name, val if not func else func(val))

        for attr in self.optional_attrs:
            __set_attr_named(attr)

        if hasattr(self, 'tag'):
            tag = getattr(self, 'tag', None)
            if tag == 'vstruct':
                self.vstruct = True

    def __repr__(self):
        return REPR_FMT % (self.__class__, hex(id(self)), self.name)


class NodeDescParamJSON(NodeDescParam):
    """Specialization for JSON syntax"""

    keywords = ['URL', 'buttonText', 'channelBox', 'conditionalVisOps',
                'conditionalLockOps', 'connectable', 'default', 'digits',
                'editable', 'help', 'hidden', 'label', 'match', 'max',
                'min', 'name', 'options', 'page', 'page_open', 'presets',
                'primvar', 'riattr', 'riopt', 'scriptText', 'shortname',
                'size', 'slidermax', 'slidermin', 'syntax', 'type', 'units',
                'widget', '_name', 'conditionalVisTrigger', 'trigger_params',
                'has_ui_struct', 'build_condvis_func']

    @staticmethod
    def valid_keyword(kwd):
        """Return True if the keyword is in the list of known tokens."""
        return kwd in NodeDescParamJSON.keywords

    def __init__(self, pdata, build_condvis_func=None):
        super(NodeDescParamJSON, self).__init__(build_condvis_func)
        self.name = None
        self.type = None
        self.size = None
        for key, val in pdata.items():
            if not self.valid_keyword(key):
                logger().warning('unknown JSON keyword: %s', key)
            setattr(self, key, val)

        self.conditionalVisOps.update(getattr(self, 'conditionalLockOps', {}))

        self._postprocess_page()
        self.finalize()

        self._postprocess_default()
        self._postprocess_options()

        # format help message
        self._format_help()

    def _postprocess_page(self):
        """The JSON syntax uses '/' to describe the page hierarchy but
        internally we use '|' to allow args file to use '/' in page names.
        This method will replace any '/' with '|'.
        """
        this_page = getattr(self, 'page', None)
        if this_page:
            setattr(self, 'page', this_page.replace('/', PAGE_SEP))

    def _postprocess_options(self):
        """check for script-based widget options
        this is a JSON-only feature.
        """
        # pylint: disable=no-member,access-member-before-definition
        if hasattr(self, 'options') and isinstance(self.options, str):
            opts = self.options.split('|')
            self.options = OrderedDict()
            if ':' in opts[0]:
                for opt in opts:
                    key, val = opt.rsplit(':', 1)
                    try:
                        self.options[key] = safe_value_eval(val)
                    except BaseException:
                        self.options[key] = val
            else:
                for key in opts:
                    self.options[key] = key
            # print '%s options=%s' % (self.name, repr(self.options))

    def _postprocess_default(self):
        """If a fixed length array has only 1 default value, assume it is valid
        for all array members."""
        if self.size and self.size > 0 and len(self.default) == 1:
            self.default = self.default * self.size

    def __repr__(self):
        return REPR_FMT % (self.__class__, hex(id(self)), self.name)

    def as_dict(self):
        """Return the param attributes as a dict."""
        out_dict = dict(vars(self))
        if '_name' in out_dict:
            out_dict['name'] = out_dict['_name']
            del out_dict['_name']
        return out_dict
