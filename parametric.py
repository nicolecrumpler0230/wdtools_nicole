import numpy as np
from bisect import bisect_left
from scipy.optimize import curve_fit
import matplotlib.pyplot as plt
from lmfit.models import VoigtModel
import pickle
import os
from sklearn.ensemble import RandomForestRegressor
from sklearn.utils import resample
import scipy
try:
	import pandas as pd
except:
	print('please install pandas to use the parametric modeule. otherwise, ignore this.')

path = os.path.abspath(__file__)
dir_path = os.path.dirname(path)

class LineProfiles:
    
    '''
    Class to fit Voigt profiles to the Balmer absorption lines of DA white dwarfs, and then infer stellar labels.

    Probabilistic prediction uses 100 boostrapped random forest models with 25 trees each, trained on 5326 spectra from the Sloan Digital Sky Survey. 
    Ground truth labels are taken from Tremblay et al. (2019)
    Line profiles are fit using the LMFIT package via chi^2 minimization. 
    '''

    def __init__(self, fit_profiles=False, training_set='Vedant',verbose = False, plot_profiles = False, n_trees = 25, n_bootstrap = 25, lines = ['alpha', 'beta', 'gamma', 'delta','epsilon','zeta','neta','theta'], optimizer = 'leastsq'):

        self.verbose = verbose
        self.optimizer = optimizer
        self.halpha = 6564.61
        self.hbeta = 4862.68
        self.hgamma = 4341.68
        self.hdelta = 4102.89
        self.hepsilon = 3971.20
        self.hzeta = 3890.12
        self.hneta = 3835.5
        self.htheta = 3799.5
        
        self.plot_profiles = plot_profiles
        self.n_trees = n_trees
        self.n_bootstrap = n_bootstrap
        self.lines = lines
        self.linedict = dict(alpha = self.halpha, beta = self.hbeta, gamma = self.hgamma, delta = self.hdelta, epsilon=self.hepsilon, zeta=self.hzeta, neta=self.hneta, theta=self.htheta)
        self.window_dict = dict(alpha = 400, beta = 400, gamma = 150, delta = 75, epsilon=50, zeta=40, neta=30, theta=20)
        self.edge_dict = dict(alpha = 200, beta = 200, gamma = 75, delta = 65, epsilon=10, zeta=10, neta=10, theta=8)

        self.features = [];
        self.line_ident = '_'
        self.fit_params = ['amp', 'center', 'sigma', 'gamma', 'fwhm', 'height']
        for linename in lines:
            self.features.append(linename[0] + '_fwhm')
            self.features.append(linename[0] + '_height')
            self.line_ident = self.line_ident + linename[0]

        self.modelname = 'bootstrap'
        self.bootstrap_models = [];
        
        if fit_profiles==False:
        #load pre-fit profiles
            try:
                self.load('rf_model_'+training_set + self.line_ident)
            except:
                print('no saved model found for this combination of lines. performing one-time initialization, training and saving model with parameters from 5326 SDSS spectra...')
                self.initialize(training_set);
        else:
            #use the fit_balmer method to generate the training set
            pass


    def linear(self, wl, p1, p2):
        return p1 + p2*wl

    def chisquare(self, residual):
        return np.sum(residual**2)

    def initialize(self,training_set):
        
        """
        Initializes the random forest models by training them on the pre-supplied dataset of parameters. This only needs to be done once for each combination of absorption lines. The model is then pickled and saved for future use in the models/ directory. 
        """
        if training_set=='Vedant':
            df = pd.read_csv(dir_path + '/models/sdss_parameters.csv')
        else:
            df = pd.read_csv(dir_path + '/models/tremblay_training_set.csv')

        targets = ['teff', 'logg']
        
        if training_set=='Vedant':
            clean = (
                (df['a_fwhm'] < 250)&
                (df['g_fwhm'] < 250)&
                (df['b_fwhm'] < 250)&
                (df['d_fwhm'] < 250)&
                (df['d_height'] < 1)&
                (df['g_height'] < 1)&
                (df['a_height'] < 1)&
                (df['b_height'] < 1)
                    )
        else:
            clean = (
                (df['a_fwhm'] < 250)&
                (df['g_fwhm'] < 250)&
                (df['b_fwhm'] < 250)&
                (df['d_fwhm'] < 250)&
                (df['e_fwhm'] < 250)&
                (df['z_fwhm'] < 250)&
                (df['n_fwhm'] < 250)&
                (df['t_fwhm'] < 250)&
                (df['t_height'] < 1)&
                (df['n_height'] < 1)&
                (df['z_height'] < 1)&
                (df['e_height'] < 1)&
                (df['d_height'] < 1)&
                (df['g_height'] < 1)&
                (df['a_height'] < 1)&
                (df['b_height'] < 1)
                    )

        X_train = np.asarray(df[clean][self.features])
        y_train = np.asarray(df[clean][targets])

        self.train(X_train, y_train)
        self.save('rf_model_'+training_set+ self.line_ident)

    def fit_line(self, wl, flux, centroid, window = 400, edges = 200, make_plot = False):
        '''
        Fit a Voigt profile around a specified centroid on the spectrum. 
        The continuum is normalized at each absorption line via a simple linear polynimial through the edges.
        Window size and edge size can be modified. 
        
        Parameters
        ---------
        wl : array
            Wavelength array of spectrum
        flux : array
            Flux array of spectrum
        centroid : float
            The theoretical centroid of the absorption line that is being fitted, in wavelength units. 
        window : float, optional
            How many Angstroms away from the line centroid are included in the fit (in both directions). This should be large enough to include the absorption line as well as 
            some continuum on either side.
        edges : float, optional
            What distance in Angstroms around each line (measured from the line center outwards) to exclude from the continuum-fitting step. This should be large enough to cover most of the 
            absorption line whilst leaving some continuum intact on either side. 
        make_plot : bool, optional
            Make a plot of the fit. 
        Returns
        -------
            lmfit `result` object
            A `result` instance from the `lmfit` package, from which fitted parameters and fit statistics can be extracted. 
        '''

        in1 = bisect_left(wl,centroid-window)
        in2 = bisect_left(wl,centroid+window)
        cropped_wl = wl[in1:in2]
        cropped_flux = flux[in1:in2]

        cmask = (cropped_wl < centroid - edges)+(cropped_wl > centroid + edges)

        p,cov = curve_fit(self.linear,cropped_wl[cmask],cropped_flux[cmask])

        continuum_normalized = 1 - (cropped_flux / self.linear(cropped_wl, p[0], p[1]))
        
        voigtfitter = VoigtModel()
        params = voigtfitter.make_params()
        params['amplitude'].set(min = 0,max = 100,value = 25)
        params['center'].set(value = centroid, max = centroid + 25, min = centroid - 25)
        params['sigma'].set(min = 0, max=200, value=10, vary = True)
        params['gamma'].set(value=10, min = 0, max=200, vary = True)

        try:
            result = voigtfitter.fit(continuum_normalized, params, x = cropped_wl, nan_policy = 'omit', method=self.optimizer)
        except:
            print('line profile fit failed! make sure the selected line is present on the provided spectrum')
            raise

        if make_plot:
            plt.figure(figsize = (6,3), )
            plt.plot(cropped_wl,1-continuum_normalized, 'k')
            plt.plot(cropped_wl,1-voigtfitter.eval(result.params, x = cropped_wl),'r')
            plt.xlabel('Wavelength ($\mathrm{\AA}$)')
            plt.ylabel('Normalized Flux')
            if centroid == self.halpha:
                plt.title(r'H$\alpha$')
            elif centroid == self.hbeta:
                plt.title(r'H$\beta$')
            elif centroid == self.hgamma:
                plt.title(r'H$\gamma$')
            elif centroid == self.hdelta:
                plt.title(r'H$\delta$')
            elif centroid == self.hepsilon:
                plt.title(r'H$\epsilon$')
            elif centroid == self.hzeta:
                plt.title(r'H$\zeta$')
            elif centroid == self.hneta:
                plt.title(r'H$\eta$')
            elif centroid == self.htheta:
                plt.title(r'H$\theta$')
            plt.show()

        return result

    def fit_balmer(self, wl, flux, make_plot = False):

        '''
        Fits Voigt profiles to the chosen Balmer lines. Returns all 18 fitted parameters. 
        
        Parameters
        ---------
        wl : array
            Wavelength array of spectrum
        flux : array
            Flux array of spectrum
        make_plot : bool, optional
            Plot all individual Balmer fits. 

        Returns
        -------
            array
            Array of Balmer parameters, 6 for each line. If the profile fit fails, returns array of `np.nan` values. 

        '''
        colnames = [];
        parameters = [];
        for linename in self.lines:
            colnames.extend([linename[0] + '_' + fparam for fparam in self.fit_params])
            try:
                line_parameters = np.asarray(self.fit_line(wl, flux, self.linedict[linename], self.window_dict[linename], self.edge_dict[linename], make_plot = make_plot).params)
                parameters.extend(line_parameters)
            except KeyboardInterrupt:
                raise
            except:
                print('profile fit failed! returning NaN...')
                parameters.extend(np.repeat(np.nan, 6))
        balmer_parameters = pd.DataFrame([parameters], columns = colnames)
        return balmer_parameters

    def train(self, x_data, y_data):
        '''
        Trains ensemble of random forests on the provided data. Does not require scaling. You shouldn't ever need to use this directly. 
        
        Parameters
        ---------
        x_data : array
            Input data, independent variables
        y_data : array
            Output data, dependent variables

        '''

        self.bootstrap_models = [];
        kernel = scipy.stats.gaussian_kde(y_data.T)
        probs = kernel.pdf(y_data.T)
        weights = 1 / probs
        weights = weights / np.nansum(weights)
        
        for i in range(self.n_bootstrap):
            idxarray = np.arange(len(x_data))
            sampleidx = np.random.choice(idxarray, size = len(idxarray), replace = True, p = weights)
            X_sample, t_sample = x_data[sampleidx], y_data[sampleidx]
            rf = RandomForestRegressor(n_estimators = self.n_trees)
            rf.fit(X_sample,t_sample)
            self.bootstrap_models.append(rf)

        print('bootstrap ensemble of random forests is trained!')

        return None

    def labels_from_parameters(self, balmer_parameters, quantile = 0.67):
        '''
        Predicts stellar labels from Balmer line parameters.
        
        Parameters
        ---------
        balmer_parameters : array
            Array of fitted Balmer parameters from the `fit_balmer` function. 

        Returns
        -------
            array
            Array of predicted stellar labels with the following format: [Teff, e_Teff, logg, e_logg]. 

        '''

        df = balmer_parameters

        balmer_parameters = np.asarray(df[self.features])

        balmer_parameters = balmer_parameters.reshape(1,-1)
        
        if np.isnan(balmer_parameters).any():
            print('NaNs detected! Aborting...')
            return np.repeat(np.nan, 4)
    

        T = [];
        predictions = [];

        for kk in range(self.n_bootstrap):
            
            ys = np.array([self.bootstrap_models[kk].estimators_[jj].predict(balmer_parameters)[0] for jj in range(self.n_trees)])
            predictions.append(np.mean(ys, 0))
            tau = np.nanmax(np.sqrt(((ys - np.nanmean(ys, 0))**2 / ((np.nanvar(ys, 0)) + 1e-10))), axis = 1)    
            T.extend(tau)
            
        predictions = np.asarray(predictions)
        T = np.asarray(T)

        T_sorted = np.sort(T)
        p = 1. * np.arange(len(T)) / (len(T) - 1)

        tauhat = np.quantile(T_sorted, quantile)
        onesigma = tauhat * np.std(predictions, 0)

        medians = np.median(predictions, 0)

        labels = np.asarray([medians[0], onesigma[0], medians[1], onesigma[1]])

        return labels


    def save(self, modelname = 'wd'):
        pickle.dump(self.bootstrap_models, open(dir_path+'/models/'+modelname+'.p', 'wb'))
        print('model saved!')

    def load(self, modelname = 'wd'):
        self.bootstrap_models = pickle.load(open(dir_path+'/models/'+modelname+'.p', 'rb'))

    def labels_from_spectrum(self, wl, flux, make_plot = False, quantile = 0.67):
        '''
        Wrapper function that directly predicts stellar labels from a provided spectrum. Performs continuum-normalization, fits Balmer profiles, and uses the bootstrap ensemble of random forests to infer labels. 
        
        Parameters
        ---------
        wl : array
            Array of spectrum wavelengths.
        fl : array
            Array of spectrum fluxes. Can be normalized or un-normalized. 
        make_plot : bool, optional
            Plot all the individual Balmer-Voigt fits. 
        quantile : float, optional
            Which quantile of the fitted labels to use for the bootstrap error estimation. Defaults to 0.67, which corresponds to a 1-sigma uncertainty. 

        Returns
        -------
            array
            Array of predicted stellar labels with the following format: [Teff, e_Teff, logg, e_logg]. 
        '''
        balmer_parameters = self.fit_balmer(wl,flux, make_plot = make_plot) 

        predictions = self.labels_from_parameters(balmer_parameters, quantile) # Deploy instantiated model. Defaults to ensemble of random forests. 

        return predictions

