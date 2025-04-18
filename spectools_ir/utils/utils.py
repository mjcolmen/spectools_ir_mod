import numpy as np
import pandas as pd
from numpy import uint,float64,float32
import os as os
from astroquery.hitran import Hitran

from astropy import units as un
from astropy.constants import c, k_B, h, u
from astropy.convolution import Gaussian1DKernel, convolve_fft
from astropy.table import Table

import matplotlib.pyplot as plt
import matplotlib as matplotlib
import sys as sys

def make_rotation_diagram(lineparams, units='mks', fluxkey='lineflux'):
    '''
    Take ouput of make_spec and use it to compute rotation diagram parameters.

    Parameters
    ---------
    lineparams: dictionary
        dictionary output from make_spec
    units : string, optional
        either 'mks', 'cgs' or 'mixed' (all mks, but wavenumber in cm-1)
    fluxkey : string, optional
        name of column in lineparams holding the line flux data

    Returns
    --------
    rot_table: astropy Table
        Table of x and y values for rotation diagram.
    '''
    if('gup' in lineparams.columns):
        gup=lineparams['gup']

    if('gp' in lineparams.columns):
        gup=lineparams['gp']

    x=lineparams['eup_k']
    y=np.log(lineparams[fluxkey]/(lineparams['wn']*1e2*gup*lineparams['a']))   #All mks
    if ('lineflux_err' in lineparams.columns):
        dy=lineparams['lineflux_err']/lineparams[fluxkey]

    if(units=='cgs'):
        y=np.log(1000.*lineparams[fluxkey]/(lineparams['wn']*gup*lineparams['a'])) #All cgs
    if(units=='mixed'):
        y=np.log(lineparams[fluxkey]/(lineparams['wn']*gup*lineparams['a'])) #Mixed units
    if ('lineflux_err' in lineparams.columns):
        dy=lineparams['lineflux_err']/lineparams[fluxkey]
        rot_dict={'x':x,'y':y,'yerr':dy,'units':units}
    else: 
        rot_dict={'x':x,'y':y,'units':units}

    return rot_dict


def compute_thermal_velocity(molecule_name, temp, isotopologue_number=1):
    '''
    Compute the thermal velocity given a molecule name and temperature

    Parameters
    ---------
    molecule_name: string
      Molecule name (e.g., 'CO', 'H2O')
    temp : float
      Temperature at which to compute thermal velocity
    isotopologue_number : float, optional
      Isotopologue number, in order of abundance in Earth's atmosphere (see HITRAN documentation for more info)
      Defaults to 1 (most common isotopologue)

    Returns
    -------
    v_thermal : float
       Thermal velocity (m/s)
    '''

    m_amu=get_molmass(molecule_name,isotopologue_number=isotopologue_number)

    mu=m_amu*u.value

    return np.sqrt(k_B.value*temp/mu)   #m/s

def markgauss(x,mean=0, sigma=1., area=1):
    '''
    Compute a Gaussian function

    Parameters
    ----------
    x : float
      x values at which to calculate the Gaussian
    mean : float, optional
      mean of Gaussian
    sigma : float, optional
      standard deviation of Gaussian
    area : float, optional
      area of Gaussian curve

    Returns
    ---------
    Gaussian function evaluated at input x values

    '''

    norm=area
    u = ( (x-mean)/np.abs(sigma) )**2
    norm = norm / (np.sqrt(2. * np.pi)*sigma)
    f=norm*np.exp(-0.5*u)

    return f

def sigma_to_fwhm(sigma):
    '''
    Convert sigma to fwhm

    Parameters
    ----------
    sigma : float
       sigma of Gaussian distribution

    Returns
    ----------
    fwhm : float
       Full Width at Half Maximum of Gaussian distribution
    '''
    return  sigma*(2.*np.sqrt(2.*np.log(2.)))

def fwhm_to_sigma(fwhm):
    '''
    Convert fwhm to sigma

    Parameters
    ----------
    fwhm : float
       Full Width at Half Maximum of Gaussian distribution

    Returns
    ----------
    sigma : float
       sigma of Gaussian distribution
    '''

    return fwhm/(2.*np.sqrt(2.*np.log(2.)))

def wn_to_k(wn):
    '''
    Convert wavenumber to Kelvin

    Parameters
    ----------
    wn : AstroPy quantity
       Wavenumber including units

    Returns
    ---------
    energy : AstroPy quantity
       Energy of photon with given wavenumber

    '''
    return wn.to(1/un.m)*h*c/k_B

def extract_hitran_data(molecule_name, wavemin, wavemax, isotopologue_number=1, eupmax=None, aupmin=None,swmin=None,vup=None):
    '''
    Extract data from HITRAN
    Primarily makes use of astroquery.hitran, with some added functionality specific to common IR spectral applications
    Parameters
    ----------
    molecule_name : string
        String identifier for molecule, for example, 'CO', or 'H2O'
    wavemin: float
        Minimum wavelength of extracted lines (in microns)
    wavemax: float
        Maximum wavelength of extracted lines (in microns)
    isotopologue_number : float, optional
        Number representing isotopologue (1=most common, 2=next most common, etc.)
    eupmax : float, optional
        Maximum extracted upper level energy (in Kelvin)
    aupmin : float, optional
        Minimum extracted Einstein A coefficient
    swmin : float, optional
        Minimum extracted line strength
    vup : float, optional
        Can be used to selet upper level energy.  Note: only works if 'Vp' string is a single number.

    Returns
    -------
    hitran_data : astropy table
        Extracted data
    '''

    #Convert molecule name to number
    M = get_molecule_identifier(molecule_name)

    #Convert inputs to astroquery formats
    min_wavenumber = 1.e4/wavemax
    max_wavenumber = 1.e4/wavemin

    #Extract hitran data using astroquery
    tbl = Hitran.query_lines(molecule_number=M,isotopologue_number=isotopologue_number,min_frequency=min_wavenumber / un.cm,max_frequency=max_wavenumber / un.cm)

    #Do some desired bookkeeping, and add some helpful columns
    tbl.rename_column('nu','wn')
    tbl['nu']=tbl['wn']*c.cgs.value   #Now actually frequency of transition
    tbl['eup_k']=(wn_to_k((tbl['wn']+tbl['elower'])/un.cm)).value

    tbl['wave']=1.e4/tbl['wn']       #Wavelength of transition, in microns
    tbl.rename_column('global_upper_quanta','Vp')
    tbl.rename_column('global_lower_quanta','Vpp')
    tbl.rename_column('local_upper_quanta','Qp')
    tbl.rename_column('local_lower_quanta','Qpp')

    #Extract desired portion of dataset
    ebool = np.full(np.size(tbl), True, dtype=bool)  #default to True
    abool = np.full(np.size(tbl), True, dtype=bool)  #default to True
    swbool = np.full(np.size(tbl), True, dtype=bool)  #default to True
    vupbool = np.full(np.size(tbl), True, dtype=bool)  #default to True
    #Upper level energy
    if(eupmax is not None):
        ebool = tbl['eup_k'] < eupmax
    #Upper level A coeff
    if(aupmin is not None):
        abool = tbl['a'] > aupmin
    #Line strength
    if(swmin is not None):
        swbool = tbl['sw'] > swmin
   #Vup
    if(vup is not None):
        vupval = [int(val) for val in tbl['Vp']]
        vupbool=(np.array(vupval)==vup)
   #Combine
    extractbool = (abool & ebool & swbool & vupbool)
    hitran_data=tbl[extractbool]

    #Return astropy table
    return hitran_data

def get_global_identifier(molecule_name,isotopologue_number=1):
    '''
    For a given input molecular formula, return the corresponding HITRAN *global* identifier number.
    For more info, see https://hitran.org/docs/iso-meta/

    Parameters
    ----------
    molecular_formula : str
        The string describing the molecule.
    isotopologue_number : int, optional
        The isotopologue number, from most to least common.

    Returns
    -------
    G : int
        The HITRAN global identifier number.
    '''

    mol_isot_code=molecule_name+'_'+str(isotopologue_number)

    trans = { 'H2O_1':1, 'H2O_2':2, 'H2O_3':3, 'H2O_4':4, 'H2O_5':5, 'H2O_6':6, 'H2O_7':129,
               'CO2_1':7,'CO2_2':8,'CO2_3':9,'CO2_4':10,'CO2_5':11,'CO2_6':12,'CO2_7':13,'CO2_8':14,
               'CO2_9':121,'CO2_10':15,'CO2_11':120,'CO2_12':122,
               'O3_1':16,'O3_2':17,'O3_3':18,'O3_4':19,'O3_5':20,
               'N2O_1':21,'N2O_2':22,'N2O_3':23,'N2O_4':24,'N2O_5':25,
               'CO_1':26,'CO_2':27,'CO_3':28,'CO_4':29,'CO_5':30,'CO_6':31,
               'CH4_1':32,'CH4_2':33,'CH4_3':34,'CH4_4':35,
               'O2_1':36,'O2_2':37,'O2_3':38,
               'NO_1':39,'NO_2':40,'NO_3':41,
               'SO2_1':42,'SO2_2':43,
               'NO2_1':44,
               'NH3_1':45,'NH3_2':46,
               'HNO3_1':47,'HNO3_2':117,
               'OH_1':48,'OH_2':49,'OH_3':50,
               'HF_1':51,'HF_2':110,
               'HCl_1':52,'HCl_2':53,'HCl_3':107,'HCl_4':108,
               'HBr_1':54,'HBr_2':55,'HBr_3':111,'HBr_4':112,
               'HI_1':56,'HI_2':113,
               'ClO_1':57,'ClO_2':58,
               'OCS_1':59,'OCS_2':60,'OCS_3':61,'OCS_4':62,'OCS_5':63,
               'H2CO_1':64,'H2CO_2':65,'H2CO_3':66,
               'HOCl_1':67,'HOCl_2':68,
               'N2_1':69,'N2_2':118,
               'HCN_1':70,'HCN_2':71,'HCN_3':72,
               'CH3Cl_1':73,'CH3CL_2':74,
               'H2O2_1':75,
               'C2H2_1':76,'C2H2_2':77,'C2H2_3':105,
               'C2H6_1':78,'C2H6_2':106,
               'PH3_1':79,
               'COF2_1':80,'COF2_2':119,
               'SF6_1':126,
               'H2S_1':81,'H2S_2':82,'H2S_3':83,
               'HCOOH_1':84,
               'HO2_1':85,
               'O_1':86,
               'ClONO2_1':127,'ClONO2_2':128,
               'NO+_1':87,
               'HOBr_1':88,'HOBr_2':89,
               'C2H4_1':90,'C2H4_2':91,
               'CH3OH_1':92,
               'CH3Br_1':93,'CH3Br_2':94,
               'CH3CN_1':95,
               'CF4_1':96,
               'C4H2_1':116,
               'HC3N_1':109,
               'H2_1':103,'H2_2':115,
               'CS_1':97,'CS_2':98,'CS_3':99,'CS_4':100,
               'SO3_1':114,
               'C2N2_1':123,
               'COCl2_1':124,'COCl2_2':125,'SiO_1':200, 'C6H6_1':300,'CH3+_1':400, 'C3H4_1':500}
 #SiO is not in HITRAN, so I just assigned it 200
 #MJCD: C6H6 and C3H4 are from Arabhavi et al (2024) and CH3+ from Changala et al. (2023)

    try:
        return trans[mol_isot_code]
    except KeyError:
        print('The molecule/isot combination ',mol_isot_code,' is not in HITRAN and not covered by this code.')
        raise KeyError

#Code from Nathan Hagen
#https://github.com/nzhagen/hitran
def translate_molecule_identifier(M):
    '''
    For a given input molecule identifier number, return the corresponding molecular formula.

    Parameters
    ----------
    M : int
        The HITRAN molecule identifier number.

    Returns
    -------
    molecular_formula : str
        The string describing the molecule.
    '''

    trans = { '1':'H2O',    '2':'CO2',   '3':'O3',      '4':'N2O',   '5':'CO',    '6':'CH4',   '7':'O2',     '8':'NO',
              '9':'SO2',   '10':'NO2',  '11':'NH3',    '12':'HNO3', '13':'OH',   '14':'HF',   '15':'HCl',   '16':'HBr',
             '17':'HI',    '18':'ClO',  '19':'OCS',    '20':'H2CO', '21':'HOCl', '22':'N2',   '23':'HCN',   '24':'CH3Cl',
             '25':'H2O2',  '26':'C2H2', '27':'C2H6',   '28':'PH3',  '29':'COF2', '30':'SF6',  '31':'H2S',   '32':'HCOOH',
             '33':'HO2',   '34':'O',    '35':'ClONO2', '36':'NO+',  '37':'HOBr', '38':'C2H4', '39':'CH3OH', '40':'CH3Br',
             '41':'CH3CN', '42':'CF4',  '43':'C4H2',   '44':'HC3N', '45':'H2',   '46':'CS',   '47':'SO3'}
    return(trans[str(M)])

#Code from Nathan Hagen
#https://github.com/nzhagen/hitran
def get_molecule_identifier(molecule_name):
    '''
    For a given input molecular formula, return the corresponding HITRAN molecule identifier number.

    Parameters
    ----------
    molecular_formula : str
        The string describing the molecule.

    Returns
    -------
    M : int
        The HITRAN molecular identifier number.
    '''

    trans = { '1':'H2O',    '2':'CO2',   '3':'O3',      '4':'N2O',   '5':'CO',    '6':'CH4',   '7':'O2',     '8':'NO',
              '9':'SO2',   '10':'NO2',  '11':'NH3',    '12':'HNO3', '13':'OH',   '14':'HF',   '15':'HCl',   '16':'HBr',
             '17':'HI',    '18':'ClO',  '19':'OCS',    '20':'H2CO', '21':'HOCl', '22':'N2',   '23':'HCN',   '24':'CH3Cl',
             '25':'H2O2',  '26':'C2H2', '27':'C2H6',   '28':'PH3',  '29':'COF2', '30':'SF6',  '31':'H2S',   '32':'HCOOH',
             '33':'HO2',   '34':'O',    '35':'ClONO2', '36':'NO+',  '37':'HOBr', '38':'C2H4', '39':'CH3OH', '40':'CH3Br',
             '41':'CH3CN', '42':'CF4',  '43':'C4H2',   '44':'HC3N', '45':'H2',   '46':'CS',   '47':'SO3'}

    ## Invert the dictionary.
    trans = {v:k for k,v in trans.items()}
    return(int(trans[molecule_name]))

def _check_hitran(molecule_name):

    hitran_list = ['H2O','CO2','O3','N2O','CO','CH4','O2','NO','SO2','NO2','NH3','HNO3','OH','HF','HCl','HBr',
             'HI','ClO','OCS','H2CO','HOCl','N2','HCN','CH3Cl',
             'H2O2','C2H2','C2H6','PH3','COF2','SF6','H2S','HCOOH',
             'HO2','O','ClONO2','NO+','HOBr','C2H4','CH3OH','CH3Br',
             'CH3CN', 'CF4','C4H2','HC3N','H2','CS','SO3']

    exomol_list=['SiO']

    geisa_list = ['C6H6']

    other_list = ['CH3+', 'C3H4']

    if(molecule_name in hitran_list):
        return 'HITRAN'
    if(molecule_name in exomol_list):
        return 'exomol'
    if(molecule_name in geisa_list):
        return 'GEISA'
    if(molecule_name in other_list):
        return 'other'
    
    else:
        return None

def spec_convol(wave,flux,dv):
    '''
    Convolve a spectrum, given wavelength in microns and flux density, by a given resolving power

    Parameters
    ---------
    wave : numpy array
        wavelength values, in microns
    flux : numpy array
        flux density values, in units of Energy/area/time/Hz
    dv : float
        Resolving power in km/s

    Returns
    --------
    newflux : numpy array
        Convolved spectrum flux density values, in same units as input

    '''
    R = c.value/(dv*1e3) #input dv in km/s, convert to m/s
    # find the minimum spacing between wavelengths in the dataset
    dws = np.abs(wave - np.roll(wave, 1))
    dw_min = np.min(dws)   #Minimum delta-wavelength between points in dataset

    fwhm = wave / R  # FWHM of resolution element as a function of wavelength ("delta lambda" in same units as wave)
    #fwhm / dw_min gives FWHM values expressed in units of minimum spacing, or the sampling for each wavelength
    #(sampling is sort of the number of data points per FWHM)
    #The sampling is different for each point in the wavelength array, because the FWHM is wavelength dependent
    #fwhm_s then gives the minimum value of the sampling - the most poorly sampled wavelength.
    fwhm_s = np.min(fwhm / dw_min)  # find mininumvalue of sampling for this dataset
    # but do not allow the sampling FWHM to be less than Nyquist
    # (i.e., make sure there are at least two points per resolution element)
    fwhm_s = np.max([2., fwhm_s])  #Will return 2 only if fwhm_s is less than 2
    #If you want all wavelengths to have the same sampling per resolution element,
    #then this ds gives the wavelength spacing for each wavelength (in units of wavelength)
    ds = fwhm / fwhm_s

    wave_constfwhm = np.cumsum(ds)+np.min(wave)

    # interpolate the flux onto the new wavelength set
    flux_constfwhm = np.interp(wave_constfwhm,wave,flux)

    # convolve the flux with a gaussian kernel; first convert the FWHM to sigma
    sigma_s = fwhm_s / 2.3548
    try:
        # for astropy < 0.4
        g = Gaussian1DKernel(width=sigma_s)
    except TypeError:
        # for astropy >= 0.4
        g = Gaussian1DKernel(sigma_s)
    # use boundary='extend' to set values outside the array to nearest array value.
    # this is the best approximation in this case.
    flux_conv = convolve_fft(flux_constfwhm, g, normalize_kernel=True, boundary='fill')
    flux_oldsampling = np.interp(wave, wave_constfwhm, flux_conv)

    return flux_oldsampling

def spec_convol_R(wave, flux, R):
    '''
    Convolve a spectrum, given wavelength in microns and flux density, by a given wavelength-dependent R

    Parameters
    ---------
    wave : numpy array
        wavelength values, in microns
    flux : numpy array
        flux density values, in units of Energy/area/time/Hz
    dv : numpy array
        Resolving power in km/s

    Returns
    --------
    newflux : numpy array
        Convolved spectrum flux density values, in same units as input

    '''
    # find the minimum spacing between wavelengths in the dataset
    dws = np.abs(wave - np.roll(wave, 1))
    dw_min = np.min(dws)   #Minimum delta-wavelength between points in dataset

    fwhm = wave / R  # FWHM of resolution element as a function of wavelength ("delta lambda" in same units as wave)
    #fwhm / dw_min gives FWHM values expressed in units of minimum spacing, or the sampling for each wavelength
    #(sampling is sort of the number of data points per FWHM)
    #The sampling is different for each point in the wavelength array, because the FWHM is wavelength dependent
    #fwhm_s then gives the minimum value of the sampling - the most poorly sampled wavelength.
    fwhm_s = np.min(fwhm / dw_min)  # find mininumvalue of sampling for this dataset
    # but do not allow the sampling FWHM to be less than Nyquist
    # (i.e., make sure there are at least two points per resolution element)
    fwhm_s = np.max([2., fwhm_s])  #Will return 2 only if fwhm_s is less than 2
    #If you want all wavelengths to have the same sampling per resolution element,
    #then this ds gives the wavelength spacing for each wavelength (in units of wavelength)
    ds = fwhm / fwhm_s

    wave_constfwhm = np.cumsum(ds)+np.min(wave)
    # interpolate the flux onto the new wavelength set
    flux_constfwhm = np.interp(wave_constfwhm,wave,flux)

    # convolve the flux with a gaussian kernel; first convert the FWHM to sigma
    sigma_s = fwhm_s / 2.3548
    try:
        # for astropy < 0.4
        g = Gaussian1DKernel(width=sigma_s)
    except TypeError:
        # for astropy >= 0.4
        g = Gaussian1DKernel(sigma_s)
    # this is the best approximation in this case.
    flux_conv = convolve_fft(flux_constfwhm, g, normalize_kernel=True, boundary='fill')
    flux_oldsampling = np.interp(wave, wave_constfwhm, flux_conv)

    return flux_oldsampling


def get_molmass(molecule_name,isotopologue_number=1):
    '''                                                                                                                          \

    For a given input molecular formula, return the corresponding molecular mass, in amu
                                                                                                                                 \

    Parameters                                                                                                                   \

    ----------                                                                                                                   \

    molecular_formula : str                                                                                                      \
        The string describing the molecule.
    isotopologue_number : int, optional
        The isotopologue number, from most to least common.                                                                      \

    Returns                                                                                                                      \

    -------                                                                                                                      \
    mu : float                                                                                                                   \
        Molecular mass in amu
    '''

    mol_isot_code=molecule_name+'_'+str(isotopologue_number)
#https://hitran.org/docs/iso-meta/

    mass = { 'H2O_1':18.010565, 'H2O_2':20.014811, 'H2O_3':19.01478, 'H2O_4':19.01674,
               'H2O_5':21.020985, 'H2O_6':20.020956, 'H2O_7':20.022915,
               'CO2_1':43.98983,'CO2_2':44.993185,'CO2_3':45.994076,'CO2_4':44.994045,
               'CO2_5':46.997431,'CO2_6':45.9974,'CO2_7':47.998322,'CO2_8':46.998291,
               'CO2_9':45.998262,'CO2_10':49.001675,'CO2_11':48.001646,'CO2_12':47.0016182378,
               'O3_1':47.984745,'O3_2':49.988991,'O3_3':49.988991,'O3_4':48.98896,'O3_5':48.98896,
               'N2O_1':44.001062,'N2O_2':44.998096,'N2O_3':44.998096,'N2O_4':46.005308,'N2O_5':45.005278,
               'CO_1':27.994915,'CO_2':28.99827,'CO_3':29.999161,'CO_4':28.99913,'CO_5':31.002516,'CO_6':30.002485,
               'CH4_1':16.0313,'CH4_2':17.034655,'CH4_3':17.037475,'CH4_4':18.04083,
               'O2_1':31.98983,'O2_2':33.994076,'O2_3':32.994045,
               'NO_1':29.997989,'NO_2':30.995023,'NO_3':32.002234,
               'SO2_1':63.961901,'SO2_2':65.957695,
               'NO2_1':45.992904,'NO2_2':46.989938,
               'NH3_1':17.026549,'NH3_2':18.023583,
               'HNO3_1':62.995644,'HNO3_2':63.99268,
               'OH_1':17.00274,'OH_2':19.006986,'OH_3':18.008915,
               'HF_1':20.006229,'HF_2':21.012404,
               'HCl_1':35.976678,'HCl_2':37.973729,'HCl_3':36.982853,'HCl_4':38.979904,
               'HBr_1':79.92616,'HBr_2':81.924115,'HBr_3':80.932336,'HBr_4':82.930289,
               'HI_1':127.912297,'HI_2':128.918472,
               'ClO_1':50.963768,'ClO_2':52.960819,
               'OCS_1':59.966986,'OCS_2':61.96278,'OCS_3':60.970341,'OCS_4':60.966371,'OCS_5':61.971231, 'OCS_6':62.966136,
               'H2CO_1':30.010565,'H2CO_2':31.01392,'H2CO_3':32.014811,
               'HOCl_1':51.971593,'HOCl_2':53.968644,
               'N2_1':28.006148,'N2_2':29.003182,
               'HCN_1':27.010899,'HCN_2':28.014254,'HCN_3':28.007933,
               'CH3Cl_1':49.992328,'CH3CL_2':51.989379,
               'H2O2_1':34.00548,
               'C2H2_1':26.01565,'C2H2_2':27.019005,'C2H2_3':27.021825,
               'C2H6_1':30.04695,'C2H6_2':31.050305,
               'PH3_1':33.997238,
               'COF2_1':65.991722,'COF2_2':66.995083,
               'SF6_1':145.962492,
               'H2S_1':33.987721,'H2S_2':35.983515,'H2S_3':34.987105,
               'HCOOH_1':46.00548,
               'HO2_1':32.997655,
               'O_1':15.994915,
               'ClONO2_1':96.956672,'ClONO2_2':98.953723,
               'NO+_1':29.997989,
               'HOBr_1':95.921076,'HOBr_2':97.919027,
               'C2H4_1':28.0313,'C2H4_2':29.034655,
               'CH3OH_1':32.026215,
               'CH3Br_1':93.941811,'CH3Br_2':95.939764,
               'CH3CN_1':41.026549,
               'CF4_1':87.993616,
               'C4H2_1':50.01565,
               'HC3N_1':51.010899,
               'H2_1':2.01565,'H2_2':3.021825,
               'CS_1':43.971036,'CS_2':45.966787,'CS_3':44.974368,'CS_4':44.970399,
               'SO3_1':79.95682,
               'C2N2_1':52.006148,
               'COCl2_1':97.9326199796,'COCl2_2':99.9296698896,
               'CS2_1':75.94414,'CS2_2':77.93994,'CS2_3':76.943256,'CS2_4':76.947495,
               'SiO_1':44.0845,'C6H6_1':78.1118, 'CH3+_1':15.0340,'C3H4_1':40.06}

    return mass[mol_isot_code]


def get_miri_mrs_resolution(wave):
    '''
    Retrieve the smallest approximate MIRI MRS spectral resolution for each unique wavelength.

    Parameters
    ---------
    wave: float or array-like
      Wavelength in microns

    Returns
    ---------
    unique_waves: array
      Unique wavelengths
    smallest_R: array
      Smallest spectral resolutions for each unique wavelength
    '''
    wave = np.array(wave, ndmin=1)

    # Define spectral resolution dictionaries. Table 3 of Pontoppidan et al. 2023 and Table 11 of Banzatti et al. 2025
    w0={
        "1A":4.90,
        "1B":5.66,
        "1C":6.53,
        "2A":7.51,
        "2B":8.67,
        "2C":10.02,
        "3A":11.55,
        "3B":13.34,
        "3C":15.41,
        "4A":17.70,
        "4B":20.69,
        "4C":24.19
        }
    w1={
        "1A":5.74,
        "1B":6.63,
        "1C":7.65,
        "2A":8.77,
        "2B":10.13,
        "2C":11.70,
        "3A":13.47,
        "3B":15.57,
        "3C":17.98,
        "4A":20.95,
        "4B":24.48,
        "4C":28.10
        }
    A={
        "1A":-19.5,
        "1B":2742.,
        "1C":-543.,
        "2A":332.,
        "2B":-331.,
        "2C":430.,
        "3A":-5120.,
        "3B":-1871.,
        "3C":-2440.,
        "4A":-2066.,
        "4B":-1076.,
        "4C":-3451.
        }
    B={
        "1A":572.,
        "1B":150.,
        "1C":601.,
        "2A":400.,
        "2B":400.,
        "2C":264.,
        "3A":633.,
        "3B":317.,
        "3C":312.,
        "4A":225.,
        "4B":150.,
        "4C":216.
        }

    # Initialization of total_wave and R arrays
    total_wave = np.empty(0)
    R = np.empty(0)

    # Calculate R and total_wave values
    for band in w0:
        mask = (wave > w0[band]) & (wave <= w1[band])
        wave_band = wave[mask]
        R_band = A[band] + B[band] * wave_band
        total_wave = np.concatenate([total_wave, wave_band])
        R = np.concatenate([R, R_band])

    # Get unique wavelengths and indices
    unique_waves, unique_indices = np.unique(total_wave, return_inverse=True)

    # Initialize an array to hold the smallest R for each unique wavelength
    smallest_R = np.full(unique_waves.shape, np.inf)

    # Fill the smallest_R array with the minimum R for each unique wavelength
    np.minimum.at(smallest_R, unique_indices, R)

    # Return the unique wavelengths and their corresponding smallest R values
    return unique_waves, smallest_R

def get_miri_mrs_wavelengths(subband):
    w0={
        "1A":4.87,
        "1B":5.62,
        "1C":6.49,
        "2A":7.45,
        "2B":8.61,
        "2C":9.91,
        "3A":11.47,
        "3B":13.25,
        "3C":15.30,
        "4A":17.54,
        "4B":20.44,
        "4C":23.84
        }
    w1={
        "1A":5.82,
        "1B":6.73,
        "1C":7.76,
        "2A":8.90,
        "2B":10.28,
        "2C":11.87,
        "3A":13.67,
        "3B":15.80,
        "3C":18.24,
        "4A":21.10,
        "4B":24.72,
        "4C":28.82
        }
    try:
        w0[subband]
    except KeyError:
        print("KeyError: Please provide a valid sub-band.")
        sys.exit(1)
    return (w0[subband],w1[subband])

def make_miri_mrs_figure(figsize=(5,5)):
    #MJCD: this function currently doesn't work with the updated get_miri_mrs_resolution
    x_1a=np.linspace(4.87,5.82,num=50)
    y_1a = [get_miri_mrs_resolution('1A',myx) for myx in x_1a]

    x_1b=np.linspace(5.62,6.73,num=50)
    y_1b = [get_miri_mrs_resolution('1B',myx) for myx in x_1b]

    x_1c=np.linspace(6.49,7.76,num=50)
    y_1c = [get_miri_mrs_resolution('1C',myx) for myx in x_1c]

    x_2a=np.linspace(7.45,8.90,num=50)
    y_2a = [get_miri_mrs_resolution('2A',myx) for myx in x_2a]

    x_2b=np.linspace(8.61,10.28,num=50)
    y_2b = [get_miri_mrs_resolution('2B',myx) for myx in x_2b]

    x_2c=np.linspace(9.91,11.87,num=50)
    y_2c = [get_miri_mrs_resolution('2C',myx) for myx in x_2c]

    x_3a=np.linspace(11.47,13.67,num=50)
    y_3a = [get_miri_mrs_resolution('3A',myx) for myx in x_3a]

    x_3b=np.linspace(13.25,15.80,num=50)
    y_3b = [get_miri_mrs_resolution('3B',myx) for myx in x_3b]

    x_3c=np.linspace(15.30,18.24,num=50)
    y_3c = [get_miri_mrs_resolution('3C',myx) for myx in x_3c]

    x_4a=np.linspace(17.54,21.10,num=50)
    y_4a = [get_miri_mrs_resolution('4A',myx) for myx in x_4a]

    x_4b=np.linspace(20.44,24.72,num=50)
    y_4b = [get_miri_mrs_resolution('4B',myx) for myx in x_4b]

    x_4c=np.linspace(23.84,28.82,num=50)
    y_4c = [get_miri_mrs_resolution('4C',myx) for myx in x_4c]

    fig=plt.figure(figsize=figsize)
    ax1=fig.add_subplot(111)
    ax1.plot(x_1a,y_1a,label='1A')
    ax1.plot(x_1b,y_1b,label='1B')
    ax1.plot(x_1c,y_1c,label='1C')
    ax1.plot(x_2a,y_2a,label='2A')
    ax1.plot(x_2b,y_2b,label='2B')
    ax1.plot(x_2c,y_2c,label='2C')
    ax1.plot(x_3a,y_3a,label='3A')
    ax1.plot(x_3b,y_3b,label='3B')
    ax1.plot(x_3c,y_3c,label='3C')
    ax1.plot(x_4a,y_4a,label='4A')
    ax1.plot(x_4b,y_4b,label='4B')
    ax1.plot(x_4c,y_4c,label='4C')

    ax1.legend()
    ax1.set_xlim(4.5,45.1)
    ax1.set_ylim(500,4500)
    ax1.set_xscale('log')
    ax1.set_xticks([5,6,7,8,9,10,20])
    ax1.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
    ax1.set_xlabel('Wavelength [$\mu$m]',fontsize=18)
    ax1.set_ylabel('Resolution (R)',fontsize=18)
    plt.show()
    return

#Modification of code from Nathan Hagen
#https://github.com/nzhagen/hitran
def extract_hitran_from_par(filename,wavemin=None,wavemax=None,isotopologue_number=1,eupmax=None,aupmin=None,swmin=None,vup=None):
    '''
    Given a HITRAN2012-format text file, read in the parameters of the molecular absorption features.

    Paramters
    ---------
    filename : str
       The filename to read in.

    Return
    ------
    data : astropy table
        The table of HITRAN data for the molecule
    ----

    '''
    if not os.path.exists:
        raise ImportError('The input filename"' + filename + '" does not exist.')

    if filename.endswith('.zip'):
        import zipfile
        zip = zipfile.ZipFile(filename, 'r')
        (object_name, ext) = os.path.splitext(os.path.basename(filename))
        #print(object_name, ext)
        filehandle = zip.read(object_name).splitlines()
    else:
        filehandle = open(filename, 'r')

    data = {'molec_id':[],        ## molecule identification number
            'local_iso_id':[],    ## isotope number
            'wn':[],              ## line center wavenumber (in cm^{-1})
            'sw':[],              ## line strength, in cm^{-1} / (molecule m^{-2})
            'a':[],          ## Einstein A coefficient (in s^{-1})
            'gamma_air':[],       ## line HWHM for air-broadening
            'gamma_self':[],      ## line HWHM for self-emission-broadening
            'elower':[],             ## energy of lower transition level (in cm^{-1})
            'n_air':[],               ## temperature-dependent exponent for "gamma-air"
            'delta_air':[],           ## air-pressure shift, in cm^{-1} / atm
            'Vp':[],              ## upper-state "global" quanta index
            'Vpp':[],             ## lower-state "global" quanta index
            'Qp':[],              ## upper-state "local" quanta index
            'Qpp':[],             ## lower-state "local" quanta index
            'ierr1':[],            ## uncertainty indices
            'ierr2':[],            ## uncertainty indices
            'ierr3':[],            ## uncertainty indices
            'ierr4':[],            ## uncertainty indices
            'ierr5':[],            ## uncertainty indices
            'ierr6':[],            ## uncertainty indices
            'iref1':[],            ## reference indices
            'iref2':[],            ## reference indices
            'iref3':[],            ## reference indices
            'iref4':[],            ## reference indices
            'iref5':[],            ## reference indices
            'iref6':[],            ## reference indices
            'line_mixing_flag':[],            ## flag
            'gp':[],              ## statistical weight of the upper state
            'gpp':[]}             ## statistical weight of the lower state

    print('Reading "' + filename + '" ...')

    for line in filehandle:
        if (len(line) < 160):
            raise ImportError('The imported file ("' + filename + '") does not appear to be a HITRAN2012-format data file.')

        data['molec_id'].append(int(line[0:2]))
        data['local_iso_id'].append(int(line[2]))
        data['wn'].append(float32(line[3:15]))
        data['sw'].append(float32(line[15:25]))
        data['a'].append(float32(line[25:35]))
        data['gamma_air'].append(float32(line[35:40]))
        data['gamma_self'].append(float32(line[40:45]))
        data['elower'].append(float32(line[45:55]))
        data['n_air'].append(float32(line[55:59]))
        data['delta_air'].append(float32(line[59:67]))
        data['Vp'].append(float32(line[67:82]))
        data['Vpp'].append(float32(line[82:97]))
        data['Qp'].append(line[97:112])
        data['Qpp'].append(line[112:127])
        data['ierr1'].append(line[127:133])
        data['ierr2'].append(line[128:133])
        data['ierr3'].append(line[129:133])
        data['ierr4'].append(line[130:133])
        data['ierr5'].append(line[131:133])
        data['ierr6'].append(line[132:133])
        data['iref1'].append(line[133:135])
        data['iref2'].append(line[135:137])
        data['iref3'].append(line[137:139])
        data['iref4'].append(line[139:141])
        data['iref5'].append(line[141:143])
        data['iref6'].append(line[143:145])
        data['line_mixing_flag'].append(line[145])
        data['gp'].append(float32(line[146:153]))
        data['gpp'].append(float32(line[153:160]))

    data=Table(data)  #convert to astropy table
    data['nu']=data['wn']*c.cgs.value   #Now actually frequency of transition
    data['eup_k']=(wn_to_k((data['wn']+data['elower'])/un.cm)).value      #upper level energy in Kelvin
    data['wave']=1.e4/data['wn']       #Wavelength of transition, in microns


    #Extract desired portion of dataset
    ebool = np.full(np.size(data), True, dtype=bool)  #default to True
    abool = np.full(np.size(data), True, dtype=bool)  #default to True
    swbool = np.full(np.size(data), True, dtype=bool)  #default to True
    vupbool = np.full(np.size(data), True, dtype=bool)  #default to True
    waveminbool = np.full(np.size(data), True, dtype=bool)  #default to True
    wavemaxbool = np.full(np.size(data), True, dtype=bool)  #default to True

    #Isotope number
    isobool = (data['local_iso_id'] == isotopologue_number)
    #Upper level energy
    if(eupmax is not None):
        ebool = data['eup_k'] < eupmax
    #Upper level A coeff
    if(aupmin is not None):
        abool = data['a'] > aupmin
    #Line strength
    if(swmin is not None):
        swbool = data['sw'] > swmin
    #Vup
    if(vup is not None):
        vupval = [int(val) for val in data['Vp']]
        vupbool = (np.array(vupval)==vup)
    #wavemin
    if(wavemin is not None):
        waveminbool=data['wave'] > wavemin
    #wavemax
    if(wavemax is not None):
        wavemaxbool=data['wave'] < wavemax

    #Combine
    extractbool = (abool & ebool & swbool & vupbool & waveminbool & wavemaxbool & isobool)
    hitran_data=data[extractbool]

    if filename.endswith('.zip'):
        zip.close()
    else:
        filehandle.close()

    return(hitran_data)

#MJCD: the CH3+ file I have is in a different format, so I made a new function to read it properly. The spectroscopic file comes from Changala et al. (2023)
def extract_hitran_ch3p(filename="data_Hitran_2020_CH3+.par",wavemin=None,wavemax=None):

    print('Reading "' + filename + '" ...')

    # Define the column widths based on the format string
    column_widths = [6, 30, 30, 11, 15, 13, 15, 15, 7, 7]
    columns = [
        "Nr", "Lev_up", "Lev_low", "wave", "Frequency", 
        "a", "eupper", "elower", "gp", "gpp"]
    
    # Read the file using fixed-width formatting
    hitran_data = pd.read_fwf(filename, widths=column_widths, skiprows=2, names=columns)
    
    hitran_data['wn'] = 1/np.array(hitran_data['wave'])*1e4
    hitran_data['elower'] = (hitran_data['elower']*k_B/h/c)/100
    hitran_data['eup_k'] = (wn_to_k((np.array(hitran_data['wn'])+np.array(hitran_data['elower']))/un.cm)).value

    #wavemin
    if(wavemin is not None):
        waveminbool=hitran_data['wave'] > wavemin
    #wavemax
    if(wavemax is not None):
        wavemaxbool=hitran_data['wave'] < wavemax

    #Combine
    extractbool = (waveminbool & wavemaxbool)
    hitran_data=hitran_data[extractbool]
    
    return hitran_data
