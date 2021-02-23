"""Classes to parse and store node descriptions.
"""

# pylint: disable=import-error

import os
import subprocess
import xml.dom.minidom as mx
from collections import OrderedDict

import rman_utils.node_desc_param
from rman_utils.node_desc_param import (
    NodeDescParamXML, NodeDescParamOSL, NodeDescParamJSON, safe_value_eval,
    NodeDescError
)
from rman_utils.filepath import FilePath
import rman_utils.json_file as json_file
from rman_utils.txmanager.txparams import TXMAKE_PRESETS
import rman_utils.logger as default_logger

default_logger.setup('rman')
__log__ = default_logger.rman_log()


def set_logger(obj):
    """Replace the default logger with another, typically to unify logging conventions.

    Arguments:
        obj {logging.logger} -- A fully configured logger
    """
    global __log__                          # pylint: disable=global-statement
    __log__ = obj
    rman_utils.node_desc_param.set_logger(obj)


def logger():
    """Return the current logger.

    Returns:
        logging.logger -- the current logger
    """
    return __log__


class NodeDescIgnore(Exception):
    """Raised when a node description should be ignored."""

    def __init__(self, value):
        super(NodeDescIgnore, self).__init__(value)
        self.value = 'NodeDesc Ignore: %s' % value

    def __str__(self):
        return str(self.value)


class DescFormat(object):
    """Encodes the original format of a node description.

    Attributes:
        Json (int): JSON file
        Osl (int): OSL (*.oso) object file.
        Xml (int): args file.
    """
    Xml = 0
    Osl = 1
    Json = 2


class DescPropType(object):
    """Encodes the type of property.

    Attributes:
        Attribute (str): RIB attribute attached to the node
        Output (str): Output parameter
        Param (str): Input parameter
    """
    Param = 'param'
    Output = 'output'
    Attribute = 'attr'


class DescNodeType(object):
    """Define all known node types."""
    kBxdf = 'bxdf'
    kDisplacement = 'displacement'
    kDisplayFilter = 'displayfilter'
    kIntegrator = 'integrator'
    kLight = 'light'
    kLightFilter = 'lightfilter'
    kPattern = 'pattern'
    kProjection = 'projection'
    kSampleFilter = 'samplefilter'
    kGlobals = 'rmanglobals'
    kDisplayChannel = 'displaychannel'
    kDisplay = 'display'


OSL_TO_RIS_TYPES = {'surface': DescNodeType.kBxdf,
                    'displacement': DescNodeType.kDisplacement,
                    'volume': DescNodeType.kBxdf,
                    'shader': DescNodeType.kPattern}


class NodeDesc(object):
    """A base class that reads node descriptions from args, oso or json files.

    Attributes:
    - name (str): Surface, PxrBlackBody, etc.
    - node_type (str): bxdf, pattern, light, etc.
    - rman_node_type (str): usually name except for metashaders.
    - params (list): list of NodeDescParam objects.
    - outputs (list): list of NodeDescParam objects.
    - attributes (list): list of NodeDescParam objects.
    - textured_params (list): names of textured params. Used by the texture \
    manager.
    """

    def __init__(self, filepath, build_condvis_func, **kwargs):
        """Takes a file path to a file of a known format (args, OSL, JSON),
        parses it and stores the data for later retrieval.

        Arguments:
            filepath {FilePath} -- full path to args or oso file.
        """
        self._name = None
        self.node_type = None
        self.rman_node_type = None
        self.help = None
        self.params = []
        self.outputs = []
        self.attributes = []
        self.param_dict = None
        self.attribute_dict = None
        self.output_dict = None
        self.textured_params = []
        self.pages_condvis_dict = {}
        self.pages_trigger_params = []
        self.ui_structs = {}
        self.ui_struct_membership = {}
        self.build_condvis_func = build_condvis_func
        # optionaly specify class to be used for params
        self.xmlparamclass = kwargs.get('xmlparamclass', NodeDescParamXML)
        self.oslparamclass = kwargs.get('oslparamclass', NodeDescParamOSL)
        self.jsonparamclass = kwargs.get('jsonparamclass', NodeDescParamJSON)
        # used by inheriting classes to parse specific bits
        self._parsed_data_type = None
        self._parsed_data = None
        # do the parsing
        self._parse_node(filepath)

    def parsed_data(self):
        """Return parsed data in its original format."""
        return self._parsed_data

    def parsed_data_type(self):
        """Return the data type as a str: 'xml', 'oso' or 'json'."""
        return self._parsed_data_type

    def clear_parsed_data(self):
        """Free parsed data to minimize memory usage.
        Should be called by the top class."""
        self._parsed_data = None

    @property
    def name(self):
        """return the node's name."""
        return self._name

    @name.setter
    def name(self, value):
        """this setter is defined to allow other attributes to be updated when
        the name is set."""
        self._name = value

    def get_param_desc(self, pname):
        """Return the NodeDescParam object for the requested input param name.
        """
        if self.param_dict is None:
            self.param_dict = {d.name: d for d in self.params}
        try:
            return self.param_dict[pname]
        except KeyError:
            return None

    def get_output_desc(self, pname):
        """Return the NodeDescParam object for the requested output param name.
        """
        if self.output_dict is None:
            self.output_dict = {d.name: d for d in self.outputs}
        try:
            return self.output_dict[pname]
        except KeyError:
            return None

    def get_attribute_desc(self, pname):
        """Return the NodeDescParam object for the requested attribute param
        name."""
        if self.attribute_dict is None:
            self.attribute_dict = {d.name: d for d in self.attributes}
        try:
            return self.attribute_dict[pname]
        except KeyError:
            return None

    def is_unique(self):
        """Return True if there must be only one instance on this node type in
        the scene."""
        return getattr(self, 'unique', False)

    def _parse_node(self, filepath):
        """Directs the incoming file toward the appropriate parsing method.

        Args:
            filepath (FilePath): Description
        """
        if filepath[-5:] == '.args':
            try:
                xmldoc = mx.parse(filepath.os_path())
            except BaseException as err:
                logger().warning('XML parsing error in %r (%s)',
                                 filepath.os_path(), err)
            else:
                self._parse_args_xml(xmldoc, filepath)
        elif filepath[-4:] == '.oso':
            self._parse_oso_file(filepath)
        elif filepath[-5:] == '.json':
            self._parse_json_file(filepath)
        # else:
        #     print 'WARNING: unknown file type: %s' % filepath

        # weed out 'notes' string attributes that are just a studio artifact.
        for i in range(len(self.params)):
            if self.params[i].name == 'notes' and self.params[i].type == 'string':
                del self.params[i]
                break

        # collect parameters triggering conditional visibility evaluation, as
        # well as arrays of structs
        # NOTE: page conditional visibility is only implemented in args files
        #       because there is no syntax (yet) for JSON and OSL.
        trigger_params_list = self.pages_trigger_params
        for prm in self.params:       # OPTIMIZE
            trigger_params_list += prm.condvis_trigger_params()
            if prm.has_ui_struct:
                struct_name = prm.uiStruct
                if struct_name not in self.ui_structs:
                    self.ui_structs[struct_name] = []
                self.ui_structs[struct_name].append(prm.name)
                self.ui_struct_membership[prm.name] = struct_name

        # loop through the params again to tag those who may trigger a
        # conditional visibility evaluation.
        trigger_params_list = list(set(trigger_params_list))
        # if trigger_params_list:
        #     print '%s triggers: %s' % (self.name, trigger_params_list)
        for prm in self.params:
            if prm.name in trigger_params_list:
                prm.condvis_set_trigger(True)

    def _parse_args_xml(self, xml, xmlfile):
        """Parse the xml contents of an args file. All parameters and outputs
        will be stored as NodeDescParam objects.

        Arguments:
            xml {xml} -- the xml document object
            xmlfile {FilePath} -- the full file path to the xml file

        Raises:
            NodeDescError: if the shaderType can not be found.
        """
        self._parsed_data = xml
        self._parsed_data_type = 'xml'

        # the node name is based on the file Name
        self.name = xmlfile.basename().rsplit('.', 1)[0]

        # get the node type (bxdf, pattern, etc)
        # we expected only one shaderType element containing a single
        # tag element. Anything else will make this code explode.
        #
        shader_types = xml.getElementsByTagName('shaderType')
        if not shader_types:
            # some args files use 'typeTag'... which one is correct ?
            shader_types = xml.getElementsByTagName('typeTag')
        if shader_types:
            tags = shader_types.item(0).getElementsByTagName('tag')
            if tags:
                self.node_type = tags.item(0).getAttribute('value')
            else:
                err = 'No "tag" element in "shaderType" ! : %s' % xmlfile
                raise NodeDescError(err)
        else:
            err = 'No "shaderType" element in args file ! : %s' % xmlfile
            raise NodeDescError(err)

        # node help
        for node in xml.firstChild.childNodes:
            if node.nodeName == 'help':
                self.help = node.firstChild.data.strip()

        # is this a metashader, i.e. an args file referencing a node
        # with a different name ?
        self.rman_node_type = self.name
        metashader = xml.getElementsByTagName('metashader')
        if metashader:
            self.rman_node_type = metashader.item(0).getAttribute('shader')

        # get the node parameters
        #
        params = xml.getElementsByTagName('param')
        for prm in params:
            obj = self.xmlparamclass(prm, self.build_condvis_func)
            self.params.append(obj)
            self._mark_if_textured(obj)

        outputs = xml.getElementsByTagName('output')
        for opt in outputs:
            obj = self.xmlparamclass(opt, self.build_condvis_func)
            self.outputs.append(obj)

        attributes = xml.getElementsByTagName('attribute')
        for att in attributes:
            obj = self.xmlparamclass(att, self.build_condvis_func)
            self.attributes.append(obj)

        pages = xml.getElementsByTagName('page')
        for page in pages:
            page_name = page.getAttribute('name')
            if page.hasAttribute('conditionalVisOp') and self.build_condvis_func:
                self.pages_condvis_dict[page_name] = {
                    'conditionalVisOp': page.getAttribute('conditionalVisOp'),
                    'conditionalVisPath': page.getAttribute('conditionalVisPath'),
                    'conditionalVisValue': safe_value_eval(
                        page.getAttribute('conditionalVisValue'))
                    }
                self.build_condvis_func(   # pylint: disable=not-callable
                    self.pages_condvis_dict[page_name], self.pages_trigger_params)
                logger().debug('%s ------------------', page_name)
                logger().debug('  |_ conditionalVisOp = %r',
                               self.pages_condvis_dict[page_name]['conditionalVisOp'])
                logger().debug('  |_ conditionalVisPath = %r',
                               self.pages_condvis_dict[page_name]['conditionalVisPath'])
                logger().debug('  |_ conditionalVisValue = %r',
                               self.pages_condvis_dict[page_name]['conditionalVisValue'])
            elif self.name == 'PxrBarnLightFilter':
                logger().debug('%s ------------------', page_name)

    def _parse_oso_file(self, oso):
        """Parse an OSL object file with the help of oslinfo. All params and
        outputs wil be stored as NodeDescParam objects.

        Arguments:
            oso {FilePath} -- full path of the *.oso file.
        """

        if not os.path.exists(oso.os_path()):
            logger().warning("OSO not found: %s", oso.os_path())
            return

        # open shader
        import oslquery as oslq
        oinfo = oslq.OslQuery()
        oinfo.open(oso)

        self._parsed_data = oinfo
        self._parsed_data_type = 'oso'

        # get name and type
        self.name = oinfo.shadername()
        self.rman_node_type = self.name
        self.node_type = OSL_TO_RIS_TYPES[oinfo.shadertype()]
        if self.node_type != DescNodeType.kPattern:
            logger().warning("WARNING: OSL %s not supported by RIS (%s)",
                             self.node_type, self.name)

        # parse params
        for i in range(oinfo.nparams()):
            param_data = oinfo.getparam(i)

            # try:
            obj = self.oslparamclass(param_data, self.build_condvis_func)
            # except BaseException as err:
            #     logger().error('Parsing failed on: %s (%s)', param_data, err)

            # struct members appear as struct.member: ignore.
            if '.' in obj.name:
                #logger().warning("not adding struct param %s" % obj.name)
                continue

            if obj.category == DescPropType.Param:
                if getattr(obj, 'lockgeom', True):
                    self.params.append(obj)
                    self._mark_if_textured(obj)
            elif obj.category == DescPropType.Output:
                self.outputs.append(obj)
            elif obj.category == DescPropType.Attribute:
                self.attributes.append(obj)
            else:
                logger().warning('WARNING: unknown category ! %s',
                                 str(obj.category))

    @staticmethod
    def _invalid_json_file_warning(validator, jsonfile):
        """output a descriptive warning when a json file is not a node file.

        Args:
        - validator (str): the contents of the json file's "$schema" field.
        - jsonfile (FilePath): the path to the json file
        """
        msg = 'Unknown json file type: %r' % validator
        if 'aovsSchema' in validator:
            msg = 'aov files should be inside a "config" directory.'
        elif 'rfmSchema' in validator:
            msg = 'rfm config files should be inside a "config" directory.'
        elif 'menuSchema' in validator:
            msg = 'menu config files should be inside a "config" directory.'
        elif 'shelfSchema' in validator:
            msg = 'shelf config files should be inside a "config" directory.'
        elif validator == '':
            fname = jsonfile.basename()
            if fname in ['extensions.json', 'mayaTranslation.json', 'syntaxDefinition.json']:
                dirnm = jsonfile.dirname()
                if dirnm.basename() == 'nodes':
                    dirnm = dirnm.dirname()
                msg = 'this file should be inside %s/config' % jsonfile.dirname()
        logger().warning('Skipping non-node file "%s": %s', jsonfile.os_path(), msg)

    def _parse_json_file(self, jsonfile):
        """Load and parse the json file. We check for a number of mandatory
        attributes, as json files will typically be used to build rfm nodes
        like render globals, displays, etc.
        We only expect params for now.

        Args:
        * jsonfile (FilePath): fully qualified path.
        """
        jdata = json_file.load(jsonfile.os_path(), ordered=True)
        # print jdata
        self._parsed_data = jdata
        self._parsed_data_type = 'json'

        # Do not parse validation schemas and json files without an appropriate
        # validation schema.
        validator = jdata.get('$schema', '')
        if validator == 'http://json-schema.org/schema#':
            # silently ignore schemas
            raise NodeDescIgnore('Schema file: %s' % jsonfile.os_path())
        elif 'rmanNodeSchema' not in validator:
            # warn the user and try to output an informative message
            self._invalid_json_file_warning(validator, jsonfile)
            raise NodeDescIgnore('Not a node file: %s' % jsonfile.os_path())

        # set mandatory attributes.
        mandatory_attr_list = ['name', 'node_type', 'rman_node_type']
        for attr in mandatory_attr_list:
            setattr(self, attr, jdata[attr])

        if 'params' in jdata:
            for pdata in jdata['params']:
                try:
                    param = self.jsonparamclass(pdata, self.build_condvis_func)
                except BaseException as err:
                    logger().error('FAILED to parse param: %s (%s)', pdata, err)
                    raise
                self.params.append(param)
                self._mark_if_textured(param)

    def _mark_if_textured(self, obj):
        opt = getattr(obj, 'options', None)
        if opt is None:
            return
        for iopt in opt:
            if iopt in TXMAKE_PRESETS.keys():
                self.textured_params.append(obj)
                logger().debug('  + %s.%s: %r in %s', self.name, obj.name, iopt,
                               TXMAKE_PRESETS.keys())
                return

    def node_help_url(self, version, root=None):
        """Return a URL to a node's help page. root can be defined to point to a
        a different URL if, for example, internet access has been disabled and
        there is a local documentation server. root can also include a pipe-separated
        extension, like in:
            'file://sw/docs|.html' > 'file://sw/docs/REN22/some_node.html'
        """
        if root is None:
            return 'https://rmanwiki.pixar.com/display/REN%s/%s' % (version, self.name)
        else:
            url_data = tuple(root.split('|'))
            if len(url_data) == 1:
                return '%s/REN%s/%s' % (url_data[0], version, self.name)
            elif len(url_data) == 2:
                return '%s/REN%s/%s%s' % (url_data[0], version, self.name, url_data[1])
            else:
                return 'https://rmanwiki.pixar.com/display/REN%s/%s' % (version, self.name)

    def as_dict(self):
        """testing method

        Returns:
            dict -- a testable ordered of the node.
        """
        dct = OrderedDict()
        dct['name'] = self.name
        dct['node_type'] = self.node_type
        dct['rman_node_type'] = self.rman_node_type
        dct['help'] = getattr(self, 'help', None)
        dct['inputs'] = OrderedDict()
        for prm in self.params:
            dct['inputs'][prm.name] = prm.as_dict()
        dct['outputs'] = OrderedDict()
        for opt in self.outputs:
            dct['outputs'][opt.name] = opt.as_dict()
        dct['attributes'] = OrderedDict()
        for attr in self.attributes:
            dct['attributes'][attr.name] = attr.as_dict()
        return dct

    def __str__(self):
        """debugging method

        Returns:
            str -- a human-readable dump of the node.
        """
        ostr = 'ShadingNode: %s ------------------------------\n' % self.name
        ostr += 'node_type: %s\n' % self.node_type
        ostr += 'rman_node_type: %s\n' % self.rman_node_type
        if hasattr(self, 'help'):
            ostr += 'help: %s\n' % self.help
        ostr += '\nINPUTS:\n'
        for prm in self.params:
            ostr += '  %s\n' % prm
        ostr += '\nOUTPUTS\n:'
        for opt in self.outputs:
            ostr += '%s\n' % opt
        ostr += '\nATTRIBUTES:\n'
        for attr in self.attributes:
            ostr += '%s\n' % attr
        ostr += '-' * 79
        return ostr

    def __repr__(self):
        return '%s object at %s (name: %s)' % (self.__class__, hex(id(self)),
                                               self.name)

#
# tests -----------------------------------------------------------------------


def _test(this=None):
    tests = [
        'PxrRectLight.args', 'PxrSurface.args', 'PxrOSLTest.oso',
        'PxrVoxelLight.args', 'lamaDielectric.args', 'PxrAttribute.oso',
        'PxrColorCorrect.oso', 'PxrLayer.oso']
    if this is not None:
        tests = [this]
    oso_path = FilePath(os.environ['RMANTREE']).join('lib', 'shaders')
    args_path = FilePath(os.environ['RMANTREE']).join('lib', 'plugins', 'Args')

    for fname in tests:
        fpath = FilePath(fname)
        if not fpath.isabs():
            if fpath.endswith('.args'):
                fpath = args_path.join(fpath)
            elif fpath.endswith('.oso'):
                fpath = oso_path.join(fpath)
            else:
                raise RuntimeError('Unknown file extension -> %s' % fpath)
        logger().info(NodeDesc(fpath, None))


# _test()