"""This module provides general functions.

These are:
    - userprint
    - compute_cov
    - smooth_cov
    - smooth_cov_wick
    - compute_ang_max
    - shuffle_distrib_forests
    - unred
See the respective docstrings for more details
"""
import os
import numpy as np
import scipy as sp
import sys
import fitsio
import glob
import healpy
import scipy.interpolate as interpolate
import iminuit


def userprint(*args, **kwds):
    """Defines an extension of the print function.

    Args:
        *args: arguments passed to print
        **kwargs: keyword arguments passed to print
    """
    print(*args, **kwds)
    sys.stdout.flush()


def compute_cov(xi, weights):
    """Computes the covariance matrix using the subsampling technique

    Args:
        xi: array of floats
            Correlation function measburement in each helpix
        weights: array of floats
            Weights on the correlation function measurement

    Returns:
        The covariance matrix
    """

    mean_xi = (xi*weights).sum(axis=0)
    sum_weights = weights.sum(axis=0)
    w = sum_weights > 0.
    mean_xi[w] /= sum_weights[w]

    meanless_xi_times_weight = weights*(xi - mean_xi)

    userprint("Computing cov...")

    covariance = meanless_xi_times_weight.T.dot(meanless_xi_times_weight)
    sum_weights_squared = sum_weights*sum_weights[:, None]
    w = sum_weights_squared > 0.
    covariance[w] /= sum_weights_squared[w]

    return covariance


def smooth_cov(xi, weights, r_par, r_trans, delta_r_trans=4.0, delta_r_par=4.0,
               covariance=None):
    """Smoothes the covariance matrix

    Args:
        xi: array of floats
            Correlation function measburement in each helpix
        weights: array of floats
            Weights on the correlation function measurement
        r_par: array of floats
            Parallel distance of each pixel of xi (in Mpc/h)
        r_par: array of floats
            Transverse distance of each pixel of xi (in Mpc/h)
        delta_r_trans: float - default: 4.0
            Variation of the transverse distance between two pixels
        delta_r_par: float - default: 4.0
            Variation of the transverse distance between two pixels
        covariance: array of floats or None - defautl: None
            Covariance matrix. If None, it will be computed using the
            subsampling technique

    Returns:
        The smooth covariance matrix. If data is not correct, then print a
        warning and return the unsmoothed covariance matrix
    """
    if covariance is None:
        covariance = compute_cov(xi, weights)

    num_bins = covariance.shape[1]
    var = np.diagonal(covariance)
    if np.any(var == 0.):
        userprint('WARNING: data has some empty bins, impossible to smooth')
        userprint('WARNING: returning the unsmoothed covariance')
        return covariance

    correlation = covariance/np.sqrt(var*var[:, None])

    correlation_smooth = np.zeros([num_bins, num_bins])


    # add together the correlation from bins with similar separations in
    # parallel and perpendicular distances
    sum_correlation = {}
    counts_correlation = {}
    for index in range(num_bins):
        userprint("\rsmoothing {}".format(index), end="")
        for index2 in range(index + 1, num_bins):
            index_delta_r_par = round(abs(r_par[index2] - r_par[index])/
                                      delta_r_par)
            index_delta_r_trans = round(abs(r_trans[index] - r_trans[index2])/
                                        delta_r_trans)
            if (index_delta_r_par, index_delta_r_trans) not in sum_correlation:
                sum_correlation[(index_delta_r_par, index_delta_r_trans)] = 0.
                counts_correlation[(index_delta_r_par, index_delta_r_trans)] = 0

            sum_correlation[(index_delta_r_par,
                             index_delta_r_trans)] += correlation[index, index2]
            counts_correlation[(index_delta_r_par, index_delta_r_trans)] += 1

    for index in range(num_bins):
        correlation_smooth[index, index] = 1.
        for index2 in range(index + 1, num_bins):
            index_delta_r_par = round(abs(r_par[index2] - r_par[index])/
                                      delta_r_par)
            index_delta_r_trans = round(abs(r_trans[index] - r_trans[index2])/
                                        delta_r_trans)
            correlation_smooth[index,
                               index2] = (sum_correlation[(index_delta_r_par,
                                                           index_delta_r_trans)]/
                                          counts_correlation[(index_delta_r_par,
                                                              index_delta_r_trans)])
            correlation_smooth[index2, index] = correlation_smooth[index,
                                                                   index2]


    userprint("\n")
    covariance_smooth = correlation_smooth * np.sqrt(var*var[:, None])
    return covariance_smooth

def smooth_cov_wick(infile,Wick_infile,outfile):
    """
    Model the missing correlation in the Wick computation
    with an exponential

    Args:
        infile (str): path to the correlation function
            (produced by picca_cf, picca_xcf)
        Wick_infile (str): path to the Wick correlation function
            (produced by picca_wick, picca_xwick)
        outfile (str): poutput path

    Returns:
        None
    """

    h = fitsio.FITS(infile)
    xi = sp.array(h[2]['DA'][:])
    weights = sp.array(h[2]['WE'][:])
    head = h[1].read_header()
    num_bins_r_par = head['NP']
    num_bins_r_trans = head['NT']
    h.close()

    covariance = compute_cov(xi,weights)

    nbin = xi.shape[1]
    var = sp.diagonal(covariance)
    if sp.any(var==0.):
        userprint('WARNING: data has some empty bins, impossible to smooth')
        userprint('WARNING: returning the unsmoothed covariance')
        return covariance

    correlation = covariance/sp.sqrt(var*var[:,None])
    cor1d = correlation.reshape(nbin*nbin)

    h = fitsio.FITS(Wick_infile)
    cow = sp.array(h[1]['CO'][:])
    h.close()

    varw = sp.diagonal(cow)
    if sp.any(varw==0.):
        userprint('WARNING: Wick covariance has bins with var = 0')
        userprint('WARNING: returning the unsmoothed covariance')
        return covariance

    corw = cow/sp.sqrt(varw*varw[:,None])
    corw1d = corw.reshape(nbin*nbin)

    Dcor1d = cor1d - corw1d

    #### indices
    ind = np.arange(nbin)
    rtindex = ind%num_bins_r_trans
    rpindex = ind//num_bins_r_trans
    idrt2d = abs(rtindex-rtindex[:,None])
    idrp2d = abs(rpindex-rpindex[:,None])
    idrt1d = idrt2d.reshape(nbin*nbin)
    idrp1d = idrp2d.reshape(nbin*nbin)

    #### reduced covariance  (50*50)
    Dcor_red1d = np.zeros(nbin)
    for idr in range(0,nbin):
        userprint("\rsmoothing {}".format(idr),end="")
        Dcor_red1d[idr] = sp.mean(Dcor1d[(idrp1d==rpindex[idr])&(idrt1d==rtindex[idr])])
    Dcor_red = Dcor_red1d.reshape(num_bins_r_par,num_bins_r_trans)
    userprint("")

    #### fit for L and A at each delta_r_par
    def corrfun(index_delta_r_par,index_delta_r_trans,L,A):
        r = sp.sqrt(float(index_delta_r_trans)**2+float(index_delta_r_par)**2) - float(index_delta_r_par)
        return A*sp.exp(-r/L)
    def chisq(L,A,index_delta_r_par):
        chi2 = 0.
        index_delta_r_par = int(index_delta_r_par)
        for index_delta_r_trans in range(1,num_bins_r_trans):
            chi = Dcor_red[index_delta_r_par,index_delta_r_trans]-corrfun(index_delta_r_par,index_delta_r_trans,L,A)
            chi2 += chi**2
        chi2 = chi2*num_bins_r_par*nbin
        return chi2

    Lfit = np.zeros(num_bins_r_par)
    Afit = np.zeros(num_bins_r_par)
    for index_delta_r_par in range(num_bins_r_par):
        m = iminuit.Minuit(chisq,L=5.,error_L=0.2,limit_L=(1.,400.),
            A=1.,error_A=0.2,
            index_delta_r_par=index_delta_r_par,fix_index_delta_r_par=True,
            userprint_level=1,errordef=1.)
        m.migrad()
        Lfit[index_delta_r_par] = m.values['L']
        Afit[index_delta_r_par] = m.values['A']

    #### hybrid covariance from wick + fit
    covariance_smooth = sp.sqrt(var*var[:,None])

    cor0 = Dcor_red1d[rtindex==0]
    for i in range(nbin):
        userprint("\rupdating {}".format(i),end="")
        for j in range(i+1,nbin):
            index_delta_r_par = idrp2d[i,j]
            index_delta_r_trans = idrt2d[i,j]
            newcov = corw[i,j]
            if (index_delta_r_trans == 0):
                newcov += cor0[index_delta_r_par]
            else:
                newcov += corrfun(index_delta_r_par,index_delta_r_trans,Lfit[index_delta_r_par],Afit[index_delta_r_par])
            covariance_smooth[i,j] *= newcov
            covariance_smooth[j,i] *= newcov

    userprint("\n")

    h = fitsio.FITS(outfile,'rw',clobber=True)
    h.write([covariance_smooth],names=['CO'],extname='COR')
    h.close()
    userprint(outfile,' written')

    return


def compute_ang_max(cosmo, r_trans_max, z_min, z_min2=None):
    """Computes the maximum anglular separation the correlation should be
    calculated to.

    This angle is given by the maximum transverse separation and the fiducial
    cosmology

    Args:
        comso: constants.Cosmo
            Fiducial cosmology
        r_trans_max: float
            Maximum transverse separation
        z_min: float
            Minimum redshift of the first set of data
        z_min2: float or None - default: None
            Minimum redshift of the second set of data. If None, use z_min

    Returns:
        The maximum anglular separation
    """
    if z_min2 is None:
        z_min2 = z_min

    r_min = cosmo.get_dist_m(z_min)
    r_min2 = cosmo.get_dist_m(z_min2)

    if r_min + r_min2 < r_trans_max:
        ang_max = np.pi
    else:
        ang_max = 2.*np.arcsin(r_trans_max/(r_min + r_min2))

    return ang_max


def shuffle_distrib_forests(data, seed):
    """Shuffles the distribution of forests by assiging the angular
        positions from another forest

    Args:
        data: dict
            A dictionary with the data. Keys are the healpix numbers of each
            spectrum. Values are lists of delta instances.
        seed: int
            Seed for the given realization of the shuffle

    Returns:
        The shuffled catalogue
    """

    userprint(("INFO: Shuffling the forests angular position with seed "
               "{}").format(seed))

    data_info = {}
    param_list = ['ra', 'dec', 'x_cart', 'y_cart', 'z_cart', 'cos_dec',
                  'thingid']
    data_info['healpix'] = []
    for param in param_list:
        data_info[param] = []

    for healpix, deltas in data.items():
        for delta in deltas:
            data_info['healpix'].append(healpix)
            for param in param_list:
                data_info[param].append(getattr(delta, param))

    np.random.seed(seed)
    new_index = np.arange(len(data_info['ra']))
    np.random.shuffle(new_index)

    index = 0
    data_shuffled = {}
    for deltas in data.values():
        for delta in deltas:
            for param in param_list:
                setattr(delta, param, data_info[param][new_index[index]])
            if not data_info['healpix'][new_index[index]] in data_shuffled:
                data_shuffled[data_info['healpix'][new_index[index]]] = []
            data_shuffled[data_info['healpix'][new_index[index]]].append(delta)
            index += 1

    return data_shuffled

def unred(wave, ebv, R_V=3.1, LMC2=False, AVGLMC=False):
    """
    https://github.com/sczesla/PyAstronomy
    in /src/pyasl/asl/unred
    """

    x = 10000./wave # Convert to inverse microns
    curve = x*0.

    # Set some standard values:
    x0 = 4.596
    gamma = 0.99
    c3 = 3.23
    c4 = 0.41
    c2 = -0.824 + 4.717/R_V
    c1 = 2.030 - 3.007*c2

    if LMC2:
        x0    =  4.626
        gamma =  1.05
        c4   =  0.42
        c3    =  1.92
        c2    = 1.31
        c1    =  -2.16
    elif AVGLMC:
        x0 = 4.596
        gamma = 0.91
        c4   =  0.64
        c3    =  2.73
        c2    = 1.11
        c1    =  -1.28

    # Compute UV portion of A(lambda)/E(B-V) curve using FM fitting function and
    # R-dependent coefficients
    xcutuv = sp.array([10000.0/2700.0])
    xspluv = 10000.0/sp.array([2700.0,2600.0])

    iuv = sp.where(x >= xcutuv)[0]
    N_UV = iuv.size
    iopir = sp.where(x < xcutuv)[0]
    Nopir = iopir.size
    if N_UV>0:
        xuv = sp.concatenate((xspluv,x[iuv]))
    else:
        xuv = xspluv

    yuv = c1 + c2*xuv
    yuv = yuv + c3*xuv**2/((xuv**2-x0**2)**2 +(xuv*gamma)**2)
    yuv = yuv + c4*(0.5392*(sp.maximum(xuv,5.9)-5.9)**2+0.05644*(sp.maximum(xuv,5.9)-5.9)**3)
    yuv = yuv + R_V
    yspluv = yuv[0:2]  # save spline points

    if N_UV>0:
        curve[iuv] = yuv[2::] # remove spline points

    # Compute optical portion of A(lambda)/E(B-V) curve
    # using cubic spline anchored in UV, optical, and IR
    xsplopir = sp.concatenate(([0],10000.0/sp.array([26500.0,12200.0,6000.0,5470.0,4670.0,4110.0])))
    ysplir = sp.array([0.0,0.26469,0.82925])*R_V/3.1
    ysplop = sp.array((sp.polyval([-4.22809e-01, 1.00270, 2.13572e-04][::-1],R_V ),
            sp.polyval([-5.13540e-02, 1.00216, -7.35778e-05][::-1],R_V ),
            sp.polyval([ 7.00127e-01, 1.00184, -3.32598e-05][::-1],R_V ),
            sp.polyval([ 1.19456, 1.01707, -5.46959e-03, 7.97809e-04, -4.45636e-05][::-1],R_V ) ))
    ysplopir = sp.concatenate((ysplir,ysplop))

    if Nopir>0:
        tck = interpolate.splrep(sp.concatenate((xsplopir,xspluv)),sp.concatenate((ysplopir,yspluv)),s=0)
        curve[iopir] = interpolate.splev(x[iopir], tck)

    #Now apply extinction correction to input flux vector
    curve *= ebv
    corr = 1./(10.**(0.4*curve))

    return corr
