# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (C) 2015-2017 GEM Foundation
#
# OpenQuake is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OpenQuake is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with OpenQuake. If not, see <http://www.gnu.org/licenses/>.

import operator
import logging
import collections
import numpy

from openquake.baselib import hdf5
from openquake.baselib.python3compat import zip, decode
from openquake.baselib.performance import Monitor
from openquake.baselib.general import groupby, get_array
from openquake.hazardlib import site, calc
from openquake.risklib import scientific, riskmodels

U8 = numpy.uint8
U16 = numpy.uint16
U32 = numpy.uint32
F32 = numpy.float32

FIELDS = ('site_id', 'lon', 'lat', 'idx', 'taxonomy_id', 'area', 'number',
          'occupants', 'deductible-', 'insurance_limit-', 'retrofitted-')

by_taxonomy = operator.attrgetter('taxonomy')


class MultiLoss(object):
    def __init__(self, loss_types, values):
        self.loss_types = loss_types
        self.values = values

    def __getitem__(self, l):
        return self.values[l]


def get_refs(assets, hdf5path):
    """
    Debugging method returning the string IDs of the assets from the datastore
    """
    with hdf5.File(hdf5path, 'r') as f:
        return f['asset_refs'][[a.idx for a in assets]]


class AssetCollection(object):
    D, I, R = len('deductible-'), len('insurance_limit-'), len('retrofitted-')

    def __init__(self, assets_by_site, cost_calculator, time_event,
                 time_events=''):
        self.cc = cost_calculator
        self.time_event = time_event
        self.time_events = time_events
        self.array, self.taxonomies = self.build_asset_collection(
            assets_by_site, time_event)
        fields = self.array.dtype.names
        self.loss_types = [f[6:] for f in fields if f.startswith('value-')]
        if 'occupants' in fields:
            self.loss_types.append('occupants')
        self.loss_types.sort()
        self.deduc = [n for n in fields if n.startswith('deductible-')]
        self.i_lim = [n for n in fields if n.startswith('insurance_limit-')]
        self.retro = [n for n in fields if n.startswith('retrofitted-')]

    def assets_by_site(self):
        """
        :returns: numpy array of lists with the assets by each site
        """
        assetcol = self.array
        site_ids = sorted(set(assetcol['site_id']))
        assets_by_site = [[] for sid in site_ids]
        index = dict(zip(site_ids, range(len(site_ids))))
        for i, ass in enumerate(assetcol):
            assets_by_site[index[ass['site_id']]].append(self[i])
        return numpy.array(assets_by_site)

    def values(self):
        """
        :returns: a composite array of asset values by loss type
        """
        loss_dt = numpy.dtype([(str(lt), float) for lt in self.loss_types])
        vals = numpy.zeros(len(self), loss_dt)  # asset values by loss_type
        for assets in self.assets_by_site():
            for asset in assets:
                for ltype in self.loss_types:
                    vals[ltype][asset.ordinal] = asset.value(
                        ltype, self.time_event)
        return vals

    def __iter__(self):
        for i in range(len(self)):
            yield self[i]

    def __getitem__(self, indices):
        if isinstance(indices, int):  # single asset
            a = self.array[indices]
            values = {lt: a['value-' + lt] for lt in self.loss_types
                      if lt != 'occupants'}
            if 'occupants' in self.array.dtype.names:
                values['occupants_' + str(self.time_event)] = a['occupants']
            return riskmodels.Asset(
                    a['idx'],
                    self.taxonomies[a['taxonomy_id']],
                    number=a['number'],
                    location=(a['lon'], a['lat']),
                    values=values,
                    area=a['area'],
                    deductibles={lt[self.D:]: a[lt] for lt in self.deduc},
                    insurance_limits={lt[self.I:]: a[lt] for lt in self.i_lim},
                    retrofitteds={lt[self.R:]: a[lt] for lt in self.retro},
                    calc=self.cc, ordinal=indices)
        new = object.__new__(self.__class__)
        new.time_event = self.time_event
        new.array = self.array[indices]
        new.taxonomies = self.taxonomies
        return new

    def __len__(self):
        return len(self.array)

    def __toh5__(self):
        # NB: the loss types do not contain spaces, so we can store them
        # together as a single space-separated string
        attrs = {'time_event': self.time_event or 'None',
                 'time_events': ' '.join(map(decode, self.time_events)),
                 'loss_types': ' '.join(self.loss_types),
                 'deduc': ' '.join(self.deduc),
                 'i_lim': ' '.join(self.i_lim),
                 'retro': ' '.join(self.retro),
                 'nbytes': self.array.nbytes}
        return dict(array=self.array, taxonomies=self.taxonomies,
                    cost_calculator=self.cc), attrs

    def __fromh5__(self, dic, attrs):
        for name in ('time_events', 'loss_types', 'deduc', 'i_lim', 'retro'):
            setattr(self, name, attrs[name].split())
        self.time_event = attrs['time_event']
        self.nbytes = attrs['nbytes']
        self.array = dic['array'].value
        self.taxonomies = dic['taxonomies'].value
        self.cc = dic['cost_calculator']

    @staticmethod
    def build_asset_collection(assets_by_site, time_event=None):
        """
        :param assets_by_site: a list of lists of assets
        :param time_event: a time event string (or None)
        :returns: two arrays `assetcol` and `taxonomies`
        """
        for assets in assets_by_site:
            if len(assets):
                first_asset = assets[0]
                break
        else:  # no break
            raise ValueError('There are no assets!')
        candidate_loss_types = list(first_asset.values)
        loss_types = []
        the_occupants = 'occupants_%s' % time_event
        for candidate in candidate_loss_types:
            if candidate.startswith('occupants'):
                if candidate == the_occupants:
                    loss_types.append('occupants')
                # discard occupants for different time periods
            else:
                loss_types.append('value-' + candidate)
        deductible_d = first_asset.deductibles or {}
        limit_d = first_asset.insurance_limits or {}
        retrofitting_d = first_asset.retrofitteds or {}
        deductibles = ['deductible-%s' % name for name in deductible_d]
        limits = ['insurance_limit-%s' % name for name in limit_d]
        retrofittings = ['retrofitted-%s' % n for n in retrofitting_d]
        float_fields = loss_types + deductibles + limits + retrofittings
        taxonomies = set()
        for assets in assets_by_site:
            for asset in assets:
                taxonomies.add(asset.taxonomy)
        sorted_taxonomies = sorted(taxonomies)
        asset_dt = numpy.dtype(
            [('idx', U32), ('lon', F32), ('lat', F32), ('site_id', U32),
             ('taxonomy_id', U32), ('number', F32), ('area', F32)] + [
                 (str(name), float) for name in float_fields])
        num_assets = sum(len(assets) for assets in assets_by_site)
        assetcol = numpy.zeros(num_assets, asset_dt)
        asset_ordinal = 0
        fields = set(asset_dt.fields)
        for sid, assets_ in enumerate(assets_by_site):
            for asset in sorted(assets_, key=operator.attrgetter('idx')):
                asset.ordinal = asset_ordinal
                record = assetcol[asset_ordinal]
                asset_ordinal += 1
                for field in fields:
                    if field == 'taxonomy_id':
                        value = sorted_taxonomies.index(asset.taxonomy)
                    elif field == 'number':
                        value = asset.number
                    elif field == 'area':
                        value = asset.area
                    elif field == 'idx':
                        value = asset.idx
                    elif field == 'site_id':
                        value = sid
                    elif field == 'lon':
                        value = asset.location[0]
                    elif field == 'lat':
                        value = asset.location[1]
                    elif field == 'occupants':
                        value = asset.values[the_occupants]
                    else:
                        try:
                            name, lt = field.split('-')
                        except ValueError:  # no - in field
                            name, lt = 'value', field
                        # the line below retrieve one of `deductibles`,
                        # `insured_limits` or `retrofitteds` ("s" suffix)
                        value = getattr(asset, name + 's')[lt]
                    record[field] = value
        return assetcol, numpy.array(sorted_taxonomies, hdf5.vstr)


def read_composite_risk_model(dstore):
    """
    :param dstore: a DataStore instance
    :returns: a :class:`CompositeRiskModel` instance
    """
    oqparam = dstore['oqparam']
    crm = dstore.getitem('composite_risk_model')
    rmdict, retrodict = {}, {}
    for taxo, rm in crm.items():
        rmdict[taxo] = {}
        retrodict[taxo] = {}
        for lt in rm:
            lt = str(lt)  # ensure Python 2-3 compatibility
            rf = dstore['composite_risk_model/%s/%s' % (taxo, lt)]
            if lt.endswith('_retrofitted'):
                # strip _retrofitted, since len('_retrofitted') = 12
                retrodict[taxo][lt[:-12]] = rf
            else:
                rmdict[taxo][lt] = rf
    return CompositeRiskModel(oqparam, rmdict, retrodict)


class CompositeRiskModel(collections.Mapping):
    """
    A container (imt, taxonomy) -> riskmodel

    :param oqparam:
        an :class:`openquake.commonlib.oqvalidation.OqParam` instance
    :param rmdict:
        a dictionary (imt, taxonomy) -> loss_type -> risk_function
    """
    def __init__(self, oqparam, rmdict, retrodict):
        self.damage_states = []
        self._riskmodels = {}

        if getattr(oqparam, 'limit_states', []):
            # classical_damage/scenario_damage calculator
            if oqparam.calculation_mode in ('classical', 'scenario'):
                # case when the risk files are in the job_hazard.ini file
                oqparam.calculation_mode += '_damage'
            self.damage_states = ['no_damage'] + oqparam.limit_states
            delattr(oqparam, 'limit_states')
            for taxonomy, ffs_by_lt in rmdict.items():
                self._riskmodels[taxonomy] = riskmodels.get_riskmodel(
                    taxonomy, oqparam, fragility_functions=ffs_by_lt)
        elif oqparam.calculation_mode.endswith('_bcr'):
            # classical_bcr calculator
            for (taxonomy, vf_orig), (taxonomy_, vf_retro) in \
                    zip(rmdict.items(), retrodict.items()):
                assert taxonomy == taxonomy_  # same imt and taxonomy
                self._riskmodels[taxonomy] = riskmodels.get_riskmodel(
                    taxonomy, oqparam,
                    vulnerability_functions_orig=vf_orig,
                    vulnerability_functions_retro=vf_retro)
        else:
            # classical, event based and scenario calculators
            for taxonomy, vfs in rmdict.items():
                for vf in vfs.values():
                    # set the seed; this is important for the case of
                    # VulnerabilityFunctionWithPMF
                    vf.seed = oqparam.random_seed
                    self._riskmodels[taxonomy] = riskmodels.get_riskmodel(
                        taxonomy, oqparam, vulnerability_functions=vfs)

        self.init(oqparam)

    def init(self, oqparam):
        self.loss_types = []
        self.curve_builders = []
        self.lti = {}  # loss_type -> idx
        self.covs = 0  # number of coefficients of variation
        self.loss_types = self.make_curve_builders(oqparam)
        taxonomies = set()
        for taxonomy, riskmodel in self._riskmodels.items():
            taxonomies.add(taxonomy)
            riskmodel.compositemodel = self
            # save the number of nonzero coefficients of variation
            for vf in riskmodel.risk_functions.values():
                if hasattr(vf, 'covs') and vf.covs.any():
                    self.covs += 1
        self.taxonomies = sorted(taxonomies)

    def get_min_iml(self):
        iml = collections.defaultdict(list)
        for taxo, rm in self._riskmodels.items():
            for lt, rf in rm.risk_functions.items():
                iml[rf.imt].append(rf.imls[0])
        return {imt: min(iml[imt]) for imt in iml}

    def make_curve_builders(self, oqparam):
        """
        Populate the inner lists .loss_types, .curve_builders.
        """
        default_loss_ratios = numpy.linspace(
            0, 1, oqparam.loss_curve_resolution + 1)[1:]
        loss_types = self._get_loss_types()
        ses_ratio = oqparam.ses_ratio if oqparam.calculation_mode in (
            'event_based_risk',) else 1
        for l, loss_type in enumerate(loss_types):
            if oqparam.calculation_mode in ('classical', 'classical_risk'):
                curve_resolutions = set()
                lines = []
                for key in sorted(self):
                    rm = self[key]
                    if loss_type in rm.loss_ratios:
                        ratios = rm.loss_ratios[loss_type]
                        curve_resolutions.add(len(ratios))
                        lines.append('%s %d' % (
                            rm.risk_functions[loss_type], len(ratios)))
                if len(curve_resolutions) > 1:  # example in test_case_5
                    logging.info(
                        'Different num_loss_ratios:\n%s', '\n'.join(lines))
                cb = scientific.CurveBuilder(
                    loss_type, max(curve_resolutions), ratios, ses_ratio,
                    True, oqparam.conditional_loss_poes,
                    oqparam.insured_losses)
            elif loss_type in oqparam.loss_ratios:  # loss_ratios provided
                cb = scientific.CurveBuilder(
                    loss_type, oqparam.loss_curve_resolution,
                    oqparam.loss_ratios[loss_type], ses_ratio, True,
                    oqparam.conditional_loss_poes, oqparam.insured_losses)
            else:  # no loss_ratios provided
                cb = scientific.CurveBuilder(
                    loss_type, oqparam.loss_curve_resolution,
                    default_loss_ratios, ses_ratio, False,
                    oqparam.conditional_loss_poes, oqparam.insured_losses)
            self.curve_builders.append(cb)
            cb.index = l
            self.lti[loss_type] = l
        return loss_types

    def get_loss_ratios(self):
        """
        :returns: a 1-dimensional composite array with loss ratios by loss type
        """
        lst = [('user_provided', numpy.bool)]
        for cb in self.curve_builders:
            lst.append((cb.loss_type, F32, len(cb.ratios)))
        loss_ratios = numpy.zeros(1, numpy.dtype(lst))
        for cb in self.curve_builders:
            loss_ratios['user_provided'] = cb.user_provided
            loss_ratios[cb.loss_type] = tuple(cb.ratios)
        return loss_ratios

    def _get_loss_types(self):
        """
        :returns: a sorted list with all the loss_types contained in the model
        """
        ltypes = set()
        for rm in self.values():
            ltypes.update(rm.loss_types)
        return sorted(ltypes)

    def __getitem__(self, taxonomy):
        return self._riskmodels[taxonomy]

    def __iter__(self):
        return iter(sorted(self._riskmodels))

    def __len__(self):
        return len(self._riskmodels)

    def build_input(self, rlzs, hazards_by_site, assetcol, eps_dict):
        """
        :param rlzs: a list of realizations
        :param hazards_by_site: an array of hazards per each site
        :param assetcol: AssetCollection instance
        :param eps_dict: a dictionary of epsilons
        :returns: a :class:`RiskInput` instance
        """
        return RiskInput(rlzs, hazards_by_site, assetcol, eps_dict)

    def gen_outputs(self, riskinput, monitor, assetcol=None):
        """
        Group the assets per taxonomy and compute the outputs by using the
        underlying riskmodels. Yield the outputs generated as dictionaries
        out_by_lr.

        :param riskinput: a RiskInput instance
        :param monitor: a monitor object used to measure the performance
        :param assetcol: not None only for event based risk
        """
        mon_context = monitor('building context')
        mon_hazard = monitor('building hazard')
        mon_risk = monitor('computing risk', measuremem=False)
        with mon_context:
            assets_by_site = (riskinput.assets_by_site if assetcol is None
                              else assetcol.assets_by_site())
            hazard_getter = riskinput.hazard_getter(
                mon_hazard(measuremem=False))
            if hasattr(hazard_getter, 'init'):  # expensive operation
                hazard_getter.init()

        # group the assets by taxonomy
        taxonomies = set()
        with monitor('grouping assets by taxonomy'):
            dic = collections.defaultdict(list)
            for i, assets in enumerate(assets_by_site):
                group = groupby(assets, by_taxonomy)
                for taxonomy in group:
                    epsgetter = riskinput.epsilon_getter(
                        [asset.ordinal for asset in group[taxonomy]])
                    dic[taxonomy].append((i, group[taxonomy], epsgetter))
                    taxonomies.add(taxonomy)
        for rlz in riskinput.rlzs:
            with mon_hazard:
                hazard = list(hazard_getter(rlz))
            for taxonomy in sorted(taxonomies):
                riskmodel = self[taxonomy]
                with mon_risk:
                    for i, assets, epsgetter in dic[taxonomy]:
                        outs = [None] * len(self.lti)
                        for lt in self.loss_types:
                            imt = riskmodel.risk_functions[lt].imt
                            haz = hazard[i].get(imt, ())
                            if len(haz):
                                out = riskmodel(lt, assets, haz, epsgetter)
                                outs[self.lti[lt]] = out
                        row = MultiLoss(self.loss_types, outs)
                        row.r = rlz.ordinal
                        row.assets = assets
                        yield row
        if hasattr(hazard_getter, 'gmfbytes'):  # for event based risk
            monitor.gmfbytes = hazard_getter.gmfbytes

    def __toh5__(self):
        loss_types = hdf5.array_of_vstr(self._get_loss_types())
        return self._riskmodels, dict(covs=self.covs, loss_types=loss_types)

    def __repr__(self):
        lines = ['%s: %s' % item for item in sorted(self.items())]
        return '<%s(%d, %d)\n%s>' % (
            self.__class__.__name__, len(lines), self.covs, '\n'.join(lines))


class PoeGetter(object):
    """
    Callable yielding dictionaries {imt: curve} when called on a realization.
    """
    def __init__(self, hazard_by_site):
        self.hazard_by_site = hazard_by_site

    def __call__(self, rlz):
        for haz in self.hazard_by_site:
            yield {imt: haz[imt][rlz] for imt in haz}


gmv_dt = numpy.dtype([('sid', U32), ('eid', U32), ('imti', U8), ('gmv', F32)])


class GmfGetter(object):
    """
    Callable yielding dictionaries {imt: array(gmv, eid)} when called
    on a realization.
    """
    dt = numpy.dtype([('gmv', F32), ('eid', U32)])

    def __init__(self, gsims, ebruptures, sitecol, imts, min_iml,
                 truncation_level, correlation_model, samples):
        self.gsims = gsims
        self.ebruptures = ebruptures
        self.sitecol = sitecol
        self.imts = imts
        self.min_iml = min_iml
        self.truncation_level = truncation_level
        self.correlation_model = correlation_model
        self.samples = samples

    def init(self):
        """
        Initialize the computers. Should be called on the workers
        """
        self.sids = self.sitecol.sids
        self.computers = []
        for ebr in self.ebruptures:
            sites = site.FilteredSiteCollection(
                ebr.sids, self.sitecol.complete)
            computer = calc.gmf.GmfComputer(
                ebr, sites, self.imts, self.gsims,
                self.truncation_level, self.correlation_model)
            self.computers.append(computer)
        self.gmfbytes = 0

    def __call__(self, rlz):
        gsim = self.gsims[rlz.ordinal]
        gmfdict = collections.defaultdict(dict)
        for computer in self.computers:
            rup = computer.rupture
            if self.samples > 1:
                eids = get_array(rup.events, sample=rlz.sampleid)['eid']
            else:
                eids = rup.events['eid']
            array = computer.compute(gsim, len(eids))  # (i, n, e)
            for imti, imt in enumerate(self.imts):
                min_gmv = self.min_iml[imti]
                for eid, gmf in zip(eids, array[imti].T):
                    for sid, gmv in zip(computer.sites.sids, gmf):
                        if gmv > min_gmv:
                            dic = gmfdict[sid]
                            if imt in dic:
                                dic[imt].append((gmv, eid))
                            else:
                                dic[imt] = [(gmv, eid)]
        for sid in self.sids:
            dic = gmfdict[sid]
            for imt in dic:
                dic[imt] = arr = numpy.array(dic[imt], self.dt)
                self.gmfbytes += arr.nbytes
            yield dic

    def get(self, rlz):
        """:returns: array of dtype gmv_dt"""
        gmfcoll = []
        for i, gmvdict in enumerate(self(rlz)):
            if gmvdict:
                sid = self.sids[i]
                for imti, imt in enumerate(self.imts):
                    for rec in gmvdict.get(imt, []):
                        gmfcoll.append((sid, rec['eid'], imti, rec['gmv']))
        return numpy.array(gmfcoll, gmv_dt)


class RiskInput(object):
    """
    Contains all the assets and hazard values associated to a given
    imt and site.

    :param rlzs: the realizations
    :param imt_taxonomies: a pair (IMT, taxonomies)
    :param hazard_by_site: array of hazards, one per site
    :param assets_by_site: array of assets, one per site
    :param eps_dict: dictionary of epsilons
    """
    def __init__(self, rlzs, hazard_by_site, assets_by_site, eps_dict):
        self.rlzs = rlzs
        self.hazard_by_site = hazard_by_site
        self.assets_by_site = assets_by_site
        self.eps = eps_dict
        taxonomies_set = set()
        aids = []
        for assets in self.assets_by_site:
            for asset in assets:
                taxonomies_set.add(asset.taxonomy)
                aids.append(asset.ordinal)
        self.aids = numpy.array(aids, numpy.uint32)
        self.taxonomies = sorted(taxonomies_set)
        self.eids = None  # for API compatibility with RiskInputFromRuptures
        self.weight = len(self.aids)

    @property
    def imt_taxonomies(self):
        """Return a list of pairs (imt, taxonomies) with a single element"""
        return [(self.imt, self.taxonomies)]

    def epsilon_getter(self, asset_ordinals):
        """
        :param asset_ordinals: list of ordinals of the assets
        :returns: a closure returning an array of epsilons from the event IDs
        """
        return lambda dummy1, dummy2: (
            [self.eps[aid] for aid in asset_ordinals]
            if self.eps else None)

    def hazard_getter(self, monitor=Monitor()):
        """
        :param monitor:
            a :class:`openquake.baselib.performance.Monitor` instance
        :returns:
            list of hazard dictionaries imt -> rlz -> haz per each site
        """
        return PoeGetter(self.hazard_by_site)

    def __repr__(self):
        return '<%s taxonomy=%s, %d asset(s)>' % (
            self.__class__.__name__, ', '.join(self.taxonomies), self.weight)


def make_eps(assets_by_site, num_samples, seed, correlation):
    """
    :param assets_by_site: a list of lists of assets
    :param int num_samples: the number of ruptures
    :param int seed: a random seed
    :param float correlation: the correlation coefficient
    :returns: epsilons matrix of shape (num_assets, num_samples)
    """
    all_assets = (a for assets in assets_by_site for a in assets)
    assets_by_taxo = groupby(all_assets, by_taxonomy)
    num_assets = sum(map(len, assets_by_site))
    eps = numpy.zeros((num_assets, num_samples), numpy.float32)
    for taxonomy, assets in assets_by_taxo.items():
        # the association with the epsilons is done in order
        assets.sort(key=operator.attrgetter('idx'))
        shape = (len(assets), num_samples)
        logging.info('Building %s epsilons for taxonomy %s', shape, taxonomy)
        zeros = numpy.zeros(shape)
        epsilons = scientific.make_epsilons(zeros, seed, correlation)
        for asset, epsrow in zip(assets, epsilons):
            eps[asset.ordinal] = epsrow
    return eps


class Gmvset(object):
    """
    Emulate a dataset containing ground motion values per event ID,
    realization ordinal and IMT index.
    """
    dt = numpy.dtype([('gmv', F32), ('eid', U32), ('rlzi', U16), ('imti', U8)])

    def __init__(self):
        self.pairs = []

    def append(self, gmv, eid, rlzi, imti):
        self.pairs.append((gmv, eid, rlzi, imti))

    @property
    def value(self):
        return numpy.array(self.pairs, self.dt)

    def __len__(self):
        return len(self.pairs)


def str2rsi(key):
    """
    Convert a string of the form 'rlz-XXXX/sid-YYYY/ZZZ'
    into a triple (XXXX, YYYY, ZZZ)
    """
    rlzi, sid, imt = key.split('/')
    return int(rlzi[4:]), int(sid[4:]), imt


def rsi2str(rlzi, sid, imt):
    """
    Convert a triple (XXXX, YYYY, ZZZ) into a string of the form
    'rlz-XXXX/sid-YYYY/ZZZ'
    """
    return 'rlz-%04d/sid-%04d/%s' % (rlzi, sid, imt)


class RiskInputFromRuptures(object):
    """
    Contains all the assets associated to the given IMT and a subsets of
    the ruptures for a given calculation.

    :param trt: a tectonic region type string
    :param rlzs_assoc: a RlzsAssoc instance
    :param imts: a list of intensity measure type strings
    :param sitecol: SiteCollection instance
    :param ses_ruptures: ordered array of EBRuptures
    :param trunc_level: truncation level for the GSIMs
    :param correl_model: correlation model for the GSIMs
    :param min_iml: an array with the minimum intensity per IMT
    :params epsilons: a matrix of epsilons (or None)
    """
    def __init__(self, trt, rlzs_assoc, imts, sitecol, ses_ruptures,
                 trunc_level, correl_model, min_iml, epsilons=None):
        assert sitecol is sitecol.complete
        self.imts = imts
        self.sitecol = sitecol
        self.ses_ruptures = numpy.array(ses_ruptures)
        grp_id = ses_ruptures[0].grp_id
        self.trt = trt
        self.trunc_level = trunc_level
        self.correl_model = correl_model
        self.min_iml = min_iml
        self.gsims = [dic[trt] for dic in rlzs_assoc.gsim_by_trt]
        self.samples = rlzs_assoc.samples[grp_id]
        self.rlzs = rlzs_assoc.get_rlzs_by_grp_id()[grp_id]
        self.weight = sum(sr.weight for sr in ses_ruptures)
        self.eids = numpy.concatenate([r.events['eid'] for r in ses_ruptures])
        if epsilons is not None:
            self.eps = epsilons  # matrix N x E, events in this block
            self.eid2idx = dict(zip(self.eids, range(len(self.eids))))

    def epsilon_getter(self, asset_ordinals):
        """
        :param asset_ordinals: ordinals of the assets
        :returns: a closure returning an array of epsilons from the event IDs
        """
        if not hasattr(self, 'eps'):
            return lambda aid, eids: None

        def geteps(aid, eids):
            return self.eps[aid, [self.eid2idx[eid] for eid in eids]]
        return geteps

    def hazard_getter(self, monitor=Monitor()):
        """
        :param monitor:
            a :class:`openquake.baselib.performance.Monitor` instance
        :returns:
            lists of N hazard dictionaries imt -> rlz -> Gmvs
        """
        return GmfGetter(self.gsims, self.ses_ruptures, self.sitecol,
                         self.imts, self.min_iml, self.trunc_level,
                         self.correl_model, self.samples)

    def __repr__(self):
        return '<%s imts=%s, weight=%d>' % (
            self.__class__.__name__, self.imts, self.weight)
