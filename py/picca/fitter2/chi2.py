from __future__ import print_function
import os.path
import scipy as sp
import iminuit
import time
import h5py
from scipy.linalg import cholesky
from scipy import random

from . import utils, priors

def _wrap_chi2(d, dic=None, k=None, pk=None, pksb=None):
    return d.chi2(k, pk, pksb, dic)

class chi2:
    def __init__(self,dic_init):
        self.zeff = dic_init['data sets']['zeff']
        self.data = dic_init['data sets']['data']
        self.par_names = sp.unique([name for d in self.data for name in d.par_names])
        self.outfile = os.path.expandvars(dic_init['outfile'])

        self.k = dic_init['fiducial']['k']
        self.pk_lin = dic_init['fiducial']['pk']
        self.pksb_lin = dic_init['fiducial']['pksb']
        self.verbosity = 1
        if 'verbosity' in dic_init:
            self.verbosity = dic_init['verbosity']

        if 'fast mc' in dic_init:
            self.nfast_mc = dic_init['fast mc']['niterations']

        if 'minos' in dic_init:
            self.minos_para = dic_init['minos']

        if 'chi2 scan' in dic_init:
            self.dic_chi2scan = dic_init['chi2 scan']

    def __call__(self, *pars):
        dic = {p:pars[i] for i,p in enumerate(self.par_names)}
        dic['SB'] = False
        chi2 = 0
        for d in self.data:
            chi2 += d.chi2(self.k,self.pk_lin,self.pksb_lin,dic)

        for prior in priors.prior_dic.values():
            chi2 += prior(dic)

        if self.verbosity == 1:
            del dic['SB']
            for p in sorted(dic.keys()):
                print(p+" "+str(dic[p]))

            print("Chi2: "+str(chi2))
            print("---\n")
        return chi2

    def _minimize(self):
        t0 = time.time()
        par_names = [name for d in self.data for name in d.pars_init]
        kwargs = {name:val for d in self.data for name, val in d.pars_init.items()}
        kwargs.update({name:err for d in self.data for name, err in d.par_error.items()})
        kwargs.update({name:lim for d in self.data for name, lim in d.par_limit.items()})
        kwargs.update({name:fix for d in self.data for name, fix in d.par_fixed.items()})

        ## do an initial "fast" minimization fixing everything except the biases
        kwargs_init = {}
        for k,v in kwargs.items():
            kwargs_init[k] = v
        for name in par_names:
            if name[:4] != "bias":
                kwargs_init["fix_"+name] = True

        mig_init = iminuit.Minuit(self,forced_parameters=self.par_names,errordef=1,**kwargs_init)
        mig_init.migrad()

        ## now get the best fit values for the biases and start a full minimization
        for name, value in mig_init.values.items():
            kwargs[name] = value

        mig = iminuit.Minuit(self,forced_parameters=self.par_names,errordef=1,**kwargs)
        fmin = mig.migrad()
        print("INFO: minimized in {}".format(time.time()-t0))
        return mig

    def minimize(self):
        self.best_fit = self._minimize()

        self.best_fit.values['SB'] = False
        for d in self.data:
            d.best_fit_model = self.best_fit.values['bao_amp']*d.xi_model(self.k, self.pk_lin-self.pksb_lin, self.best_fit.values)

            self.best_fit.values['SB'] = True
            snl = self.best_fit.values['sigmaNL_per']
            self.best_fit.values['sigmaNL_per'] = 0
            d.best_fit_model += d.xi_model(self.k, self.pksb_lin, self.best_fit.values)
            self.best_fit.values['SB'] = False
            self.best_fit.values['sigmaNL_per'] = snl
        del self.best_fit.values['SB']

    def chi2scan(self):
        if not hasattr(self, "dic_chi2scan"): return

        dim = len(self.dic_chi2scan)

        ### Set all parameters to the minimum and store the current state
        store_data_pars = {}
        for d in self.data:
            store_d_pars_init = {}
            store_d_par_error = {}
            store_d_par_fixed = {}
            for name in d.pars_init.keys():
                store_d_pars_init[name] = d.pars_init[name]
                d.pars_init[name] = self.best_fit.values[name]
            for name in d.par_error.keys():
                store_d_par_error[name] = d.par_error[name]
                d.par_error[name] = self.best_fit.errors[name.split('error_')[1]]
            for name in d.par_fixed.keys():
                store_d_par_fixed[name] = d.par_fixed[name]
            store_data_pars[d.name] = {'init':store_d_pars_init, 'error':store_d_par_error, 'fixed':store_d_par_fixed}

        ###
        for p in self.dic_chi2scan.keys():
            for d in self.data:
                if 'error_'+p in d.par_error.keys():
                    d.par_error['error_'+p] = 0.
                if 'fix_'+p in d.par_fixed.keys():
                    d.par_fixed['fix_'+p] = True

        ###
        def send_one_fit():
            try:
                best_fit = self._minimize()
                chi2_result = best_fit.fval
            except:
                chi2_result = sp.nan
            tresult = []
            for p in sorted(best_fit.values):
                tresult += [best_fit.values[p]]
            tresult += [chi2_result]
            return tresult

        result = []
        ###
        if dim==1:
            par = list(self.dic_chi2scan.keys())[0]
            for step in self.dic_chi2scan[par]['grid']:
                for d in self.data:
                    if par in d.pars_init.keys():
                        d.pars_init[par] = step
                result += [send_one_fit()]
        elif dim==2:
            par1  = list(self.dic_chi2scan.keys())[0]
            par2  = list(self.dic_chi2scan.keys())[1]
            for step1 in self.dic_chi2scan[par1]['grid']:
                for step2 in self.dic_chi2scan[par2]['grid']:
                    for d in self.data:
                        if par1 in d.pars_init.keys():
                            d.pars_init[par1] = step1
                        if par2 in d.pars_init.keys():
                            d.pars_init[par2] = step2
                    result += [send_one_fit()]

        self.dic_chi2scan_result = {}
        self.dic_chi2scan_result['params'] = sp.asarray(sp.append(sorted(self.best_fit.values),['fval']))
        self.dic_chi2scan_result['values'] = sp.asarray(result)

        ### Set all parameters to where they were before
        for d in self.data:
            store_d_pars_init = store_data_pars[d.name]['init']
            store_d_par_error = store_data_pars[d.name]['error']
            store_d_par_fixed = store_data_pars[d.name]['fixed']
            for name in d.pars_init.keys():
                d.pars_init[name] = store_d_pars_init[name]
            for name in d.par_error.keys():
                d.par_error[name] = store_d_par_error[name]
            for name in d.par_fixed.keys():
                d.par_fixed[name] = store_d_par_fixed[name]

    def fastMC(self):
        if not hasattr(self,"nfast_mc"): return

        nfast_mc = self.nfast_mc
        for d in self.data:
            d.cho = cholesky(d.co)

        self.fast_mc = {}
        for it in range(nfast_mc):
            for d in self.data:
                g = random.randn(len(d.da))
                d.da = d.cho.dot(g) + d.best_fit_model
                d.da_cut = d.da[d.mask]

            best_fit = self._minimize()
            for p, v in best_fit.values.items():
                if not p in self.fast_mc:
                    self.fast_mc[p] = []
                self.fast_mc[p].append([v, best_fit.errors[p]])

    def minos(self):
        if not hasattr(self,"minos_para"): return

        sigma = self.minos_para['sigma']
        if 'all' in self.minos_para['parameters']:
            self.best_fit.minos(var=None,sigma=sigma)
        else:
            for var in self.minos_para['parameters']:
                if var in self.best_fit.list_of_vary_param():
                    self.best_fit.minos(var=var,sigma=sigma)
                else:
                    if var in self.best_fit.list_of_fixed_param():
                        print('WARNING: Can not run minos on a fixed parameter: {}'.format(var))
                    else:
                        print('WARNING: Can not run minos on a unknown parameter: {}'.format(var))

    def export(self):
        f = h5py.File(self.outfile,"w")

        g=f.create_group("best fit")

        ## write down all parameters
        for i, p in enumerate(self.best_fit.values):
            v = self.best_fit.values[p]
            e = self.best_fit.errors[p]
            if p in self.best_fit.list_of_fixed_param():
                e = 0
            g.attrs[p] = (v, e)

        for (p1, p2), cov in self.best_fit.covariance.items():
            g.attrs["cov[{}, {}]".format(p1,p2)] = cov

        ndata = [d.mask.sum() for d in self.data]
        ndata = sum(ndata)
        g.attrs['zeff'] = self.zeff
        g.attrs['ndata'] = ndata
        g.attrs['npar'] = len(self.best_fit.list_of_vary_param())
        g.attrs['list of free pars'] = [a.encode('utf8') for a in self.best_fit.list_of_vary_param()]
        g.attrs['list of fixed pars'] = [a.encode('utf8') for a in self.best_fit.list_of_fixed_param()]
        if len(priors.prior_dic) != 0:
            g.attrs['list of prior pars'] = [a.encode('utf8') for a in priors.prior_dic.keys()]

        ## write down all attributes of the minimum
        dic_fmin = utils.convert_instance_to_dictionary(self.best_fit.get_fmin())
        for item, value in dic_fmin.items():
            g.attrs[item] = value

        self.best_fit.values['SB'] = False
        for d in self.data:
            g = f.create_group(d.name)
            g.attrs['ndata'] = d.mask.sum()
            g.attrs['chi2'] = d.chi2(self.k, self.pk_lin, self.pksb_lin, self.best_fit.values)
            fit = g.create_dataset("fit", d.da.shape, dtype = "f")
            fit[...] = d.best_fit_model
        del self.best_fit.values['SB']

        if hasattr(self, "fast_mc"):
            g = f.create_group("fast mc")
            for p in self.fast_mc:
                vals = sp.array(self.fast_mc[p])
                d = g.create_dataset("{}/values".format(p), vals[:,0].shape, dtype="f")
                d[...] = vals[:,0]
                d = g.create_dataset("{}/errors".format(p), vals[:,1].shape, dtype="f")
                d[...] = vals[:,1]

        ## write down all attributes of parameters minos was run over
        if hasattr(self, "minos_para"):
            g = f.create_group("minos")
            g.attrs['sigma'] = self.minos_para['sigma']
            minos_results = self.best_fit.get_merrors()
            for par in list(minos_results.keys()):
                subgrp = g.create_group(par)
                dic_minos = utils.convert_instance_to_dictionary(minos_results[par])
                for item, value in dic_minos.items():
                    subgrp.attrs[item] = value

        if hasattr(self, "dic_chi2scan"):
            g = f.create_group("chi2 scan")
            for p, dic in self.dic_chi2scan.items():
                subgrp = g.create_group(p)
                subgrp.attrs['min']    = dic['min']
                subgrp.attrs['max']    = dic['max']
                subgrp.attrs['nb_bin'] = dic['nb_bin']
            subgrp = g.create_group('result')
            params = self.dic_chi2scan_result['params']
            for i,p in enumerate(params):
                subgrp.attrs[p] = i
            values = self.dic_chi2scan_result['values']
            vals = subgrp.create_dataset("values", values.shape, dtype = "f")
            vals[...] = values

        f.close()
