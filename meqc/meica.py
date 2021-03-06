#!/usr/bin/env python

import os
import sys
import glob
import re
import argparse

import nibabel as nib
import numpy as np


def fparse(fname):
    """
    Filename parser for NIFTI and AFNI files.

    Returns prefix from input datafiles (e.g., sub_001) and filetype (e.g.,
    .nii). If AFNI format is supplied, extracts space (+tlrc, +orig, or +mni)
    as filetype.

    Parameters
    ----------
    fname : str

    Returns
    -------
    str, str: prefix of filename, type of filename
    """

    if '.' in fname:
        if '+' in fname:  # i.e., if AFNI format
            prefix = fname.split('+')[0]
            suffix = ''.join(fname.split('+')[-1:])
            ftype  = '+' + suffix.split('.')[0]
        else:
            if fname.endswith('.gz'):  # if gzipped, two matches for ftype
                prefix = '.'.join(fname.split('.')[:-2])
                ftype  = '.' + '.'.join(fname.split('.')[-2:])
            else:
                prefix = '.'.join(fname.split('.')[:-1])
                ftype  = '.' + ''.join(fname.split('.')[-1:])
    else:
        prefix = fname
        ftype  = ''

    return prefix, ftype


def format_inset(inset, tes=None, e=0):
    """
    Parse input file specification as short- or longhand.

    Given a dataset specification (usually from options.input_ds),
    parse and create a setname for all output files. Also optionally takes
    a label to append to all created files.

    Parameters
    ----------
    inset : str
    tes   : str
    e     : echo to process, default 1

    Returns
    -------
    str: dataset name
    str: name to be "set" for any output files
    """
    try:
        # Parse shorthand input file specification
        if '[' in inset:
            fname, ftype = fparse(inset)
            if '+' in ftype:  # if AFNI format, call .HEAD file
                ftype = ftype + '.HEAD'
            prefix       = re.split(r'[\[\],]',fname)[0]
            echo_nums    = re.split(r'[\[\],]',fname)[1:-1]
            trailing     = re.split(r'[\]+]',fname)[-1]
            dsname       = prefix + echo_nums[e] + trailing + ftype
            setname      = prefix + ''.join(echo_nums) + trailing

        # Parse longhand input file specificiation
        else:
            datasets_in   = inset.split(',')
            prefix, ftype = fparse(datasets_in[0])
            echo_nums     = [str(vv+1) for vv in range(len(tes))]
            trailing      = ''
            dsname        = datasets_in[e].strip()
            setname       = prefix + ''.join(echo_nums[1:]) + trailing
            assert len(echo_nums) == len(datasets_in)

    except AssertionError as err:
            print("*+ Can't understand dataset specification. "            +
                  "Number of TEs and input datasets must be equal and "    +
                  "matched in order. Try double quotes around -d argument.")
            raise err

    return dsname, setname


def check_obliquity(fname):
    """
    Generates obliquity (in degrees) of `fname`

    Parameters
    ----------
    fname : str
        path to neuroimage

    Returns
    -------
    float : angle from plumb (in degrees)
    """

    # get abbreviated affine matrix (3x3)
    aff = nib.load(fname).affine[:3,:-1]

    # generate offset (rads) and convert to degrees
    fig_merit = np.min(np.sqrt((aff**2).sum(axis=0)) / np.abs(aff).max(axis=0))
    ang_merit = (np.arccos(fig_merit) * 180) / np.pi

    return ang_merit


def find_CM(fname):
    """
    Generates center of mass for `fname`

    Will only use the first volume if a 4D image is supplied

    Parameters
    ----------
    fname : str
        path to neuroimage

    Returns
    -------
    float, float, float : x, y, z coordinates of center of mass
    """

    im = nib.load(fname)
    data = im.get_data()
    if data.ndim > 3: data = data[:,:,:,0]  # use first volume in 4d series
    data_sum = data.sum()  # to ensure the dataset is non-zero

    # if dataset is not simply zero, then calculate CM in i, j, k values
    # otherwise, just pick the dead center of the array
    if data_sum > 0:
        cm = []  # to hold CMs
        for n, dim in enumerate(im.shape[:3]):
            res = np.ones(3,dtype='int')  # create matrix for reshaping
            res[n] = dim                  # set appropriate dimension to dim
            cm.append((np.arange(dim).reshape(res) * data).sum()/data_sum)
    else:
        cm = 0.5*(np.array(im.shape[:3])-1)

    # for some reason, the affine as read by nibabel is different than AFNI;
    # specifically, the first two rows are inverted, so we invert them back
    # (since we're trying to do this as AFNI would)
    # then, we calculate the orientation, reindex the affine matrix, and
    # generate the centers of mass from there based on the above calculations
    affine = im.affine * [[-1],[-1],[1],[1]]             # fix affine
    orient = np.abs(affine).argsort(axis=0)[-1,:3]       # get orientation
    affine = affine[orient]                              # reindex affine
    cx, cy, cz = affine[:,-1] + cm * np.diag(affine)     # calculate centers
    cx, cy, cz = np.array([cx,cy,cz])[orient.argsort()]  # reorient centers

    return cx, cy, cz


def get_options(_debug=None):
    """
    Parses command line inputs

    Returns
    -------
    argparse dic
    """

    # Configure options and help dialog
    parser = argparse.ArgumentParser()

    # Base processing options
    parser.add_argument('-e',
                        dest='tes',
                        help="Echo times in ms. ex: -e 14.5,38.5,62.5",
                        default="")
    parser.add_argument('-d',
                        dest='input_ds',
                        help="Input datasets. ex: -d RESTe[123].nii.gz",
                        default='')
    parser.add_argument('-a',
                        dest='anat',
                        help="(Optional) anatomical dataset. " +
                             "ex: -a mprage.nii.gz",
                        default='')
    parser.add_argument('-b',
                        dest='basetime',
                        help="Time to steady-state equilibration in " +
                             "seconds(s) or volumes(v). Default 0. ex: -b 4v",
                        default='0')
    parser.add_argument('--MNI',
                        dest='mni',
                        action='store_true',
                        help="Warp to MNI standard space.",
                        default=False)
    parser.add_argument('--strict',
                        dest='strict',
                        action='store_true',
                        help="Use strict component selection, suitable with" +
                             " large-voxel, high-SNR data",
                        default=False)

    # Extended options for processing
    extopts = parser.add_argument_group("Additional processing options")
    extopts.add_argument("--qwarp",
                         dest='qwarp',
                         action='store_true',
                         help="Nonlinear warp to standard space using QWarp," +
                              " requires --MNI or --space).",
                         default=False)
    extopts.add_argument("--native",
                         dest='native',
                         action='store_true',
                         help="Output native space results in addition to " +
                              "standard space results.",
                         default=False)
    extopts.add_argument("--space",
                         dest='space',
                         help="Path to specific standard space template for " +
                              "affine anatomical normalization.",
                         default=False)
    extopts.add_argument("--fres",
                         dest='fres',
                         help="Specify functional voxel dimensions in mm " +
                              "(iso.) for resampling during preprocessing." +
                              "ex: --fres=2.5",
                         default=False)
    extopts.add_argument("--no_skullstrip",
                         action="store_true",
                         dest='no_skullstrip',
                         help="Anat is intensity-normalized and " +
                              "skull-stripped (for use with '-a' flag).",
                         default=False)
    extopts.add_argument("--no_despike",
                         action="store_true",
                         dest='no_despike',
                         help="Do not de-spike functional data. " +
                              "Default is to de-spike, recommended.",
                         default=False)
    extopts.add_argument("--no_axialize",
                         action="store_true",
                         dest='no_axialize',
                         help="Do not re-write dataset in axial-first order." +
                              " Default is to axialize, recommended.",
                         default=False)
    extopts.add_argument("--mask_mode",
                         dest='mask_mode',
                         help="Mask functional with help from anatomical or" +
                              " standard space images." +
                              " Options: 'anat' or 'template'.",
                         default='func')
    extopts.add_argument("--coreg_mode",
                         dest='coreg_mode',
                         help="Coregistration with Local Pearson and T2* weights "+
                              "(default), or use align_epi_anat.py (edge method)."+
                              "Options: 'lp-t2s' or 'aea'",
                         default='lp-t2s')
    extopts.add_argument("--smooth",
                         dest='FWHM',
                         help="FWHM smoothing with 3dBlurInMask. Default none. " +
                              "ex: --smooth 3mm ",
                         default='0mm')
    extopts.add_argument("--align_base",
                         dest='align_base',
                         help="Explicitly specify base dataset for volume " +
                              "registration",
                         default='')
    extopts.add_argument("--TR",
                         dest='TR',
                         help="TR. Read by default from dataset header",
                         default='')
    extopts.add_argument("--tpattern",
                         dest='tpattern',
                         help="Slice timing (i.e. alt+z, see 3dTshift -help)." +
                              " Default from header.",
                         default='')
    extopts.add_argument("--align_args",
                         dest='align_args',
                         help="Additional arguments to anatomical-functional" +
                              " co-registration routine",
                         default='')
    extopts.add_argument("--ted_args",
                         dest='ted_args',
                         help="Additional arguments to " +
                              "TE-dependence analysis",
                         default='')

    # Additional, extended preprocessing options
    #  no help provided, caveat emptor
    extopts.add_argument("--select_only",
                         dest='select_only',
                         action='store_true',
                         help=argparse.SUPPRESS,
                         default=False)
    extopts.add_argument("--tedica_only",
                         dest='tedica_only',
                         action='store_true',
                         help=argparse.SUPPRESS,
                         default=False)
    extopts.add_argument("--export_only",
                         dest='export_only',
                         action='store_true',
                         help=argparse.SUPPRESS,
                         default=False)
    extopts.add_argument("--daw",
                         dest='daw',
                         help=argparse.SUPPRESS,
                         default='10')
    extopts.add_argument("--tlrc",
                         dest='space',
                         help=argparse.SUPPRESS,
                         default=False)  # For backwards compat.
    extopts.add_argument("--highpass",
                         dest='highpass',
                         help=argparse.SUPPRESS,
                         default=0.0)
    extopts.add_argument("--detrend",
                         dest='detrend',
                         help=argparse.SUPPRESS,
                         default=0.)
    extopts.add_argument("--initcost",
                         dest='initcost',
                         help=argparse.SUPPRESS,
                         default='tanh')
    extopts.add_argument("--finalcost",
                         dest='finalcost',
                         help=argparse.SUPPRESS,
                         default='tanh')
    extopts.add_argument("--sourceTEs",
                         dest='sourceTEs',
                         help=argparse.SUPPRESS,
                         default='-1')
    parser.add_argument_group(extopts)

    # Extended options for running
    runopts = parser.add_argument_group("Run options")
    runopts.add_argument("--prefix",
                         dest='prefix',
                         help="Prefix for final ME-ICA output datasets.",
                         default='')
    runopts.add_argument("--cpus",
                         dest='cpus',
                         help="Maximum number of CPUs (OpenMP threads) to use. " +
                         "Default 2.",
                         default='2')
    runopts.add_argument("--label",
                         dest='label',
                         help="Label to tag ME-ICA analysis folder.",
                         default='')
    runopts.add_argument("--test_proc",
                         action="store_true",
                         dest='test_proc',
                         help="Align, preprocess 1 dataset then exit.",
                         default=False)
    runopts.add_argument("--pp_only",
                         action="store_true",
                         dest='preproc_only',
                         help="Preprocess only, then exit.",
                         default=False)
    runopts.add_argument("--keep_int",
                         action="store_true",
                         dest='keep_int',
                         help="Keep preprocessing intermediates. " +
                              "Default delete.",
                              default=False)
    runopts.add_argument("--RESUME",
                         dest='resume',
                         action='store_true',
                         help="Attempt to resume from normalization step " +
                              "onwards, overwriting existing")
    runopts.add_argument("--OVERWRITE",
                         dest='overwrite',
                         action="store_true",
                         help="Overwrite existing meica directory.",
                         default=False)
    parser.add_argument_group(runopts)

    if _debug is not None: return parser.parse_args(_debug)
    else: return parser.parse_args()


def gen_script(options):
    """
    Parses input options to generate working ME-ICA script based on inputs

    Parameters
    ----------
    options : argparse
        from get_options()

    Returns
    -------
    list : ME-ICA script for input data
    """

    # Check for required input data
    for echo in range(len(options.tes.split(','))):
        dataset, _setname = format_inset(options.input_ds,
                                         options.tes.split(','),
                                         e=echo)
        if not os.path.isfile(dataset):
            raise OSError("*+ Can't find dataset {}!".format(dataset))

    # Set current paths, create logfile for use as shell script
    startdir  = str(os.getcwd())
    meicadir  = str(os.path.dirname(os.path.realpath(__file__)))
    # out_ftype = '.nii.gz'  # Set NIFTI as default output filetype

    script_list = []
    # script_list.append('# Selected Options: ' + args)

    # Generate output filenames
    _dsname, setname = format_inset(options.input_ds,
                                    options.tes.split(','))
    if options.label != '':
        setname = setname + options.label

    output_prefix = options.prefix

    # Parse timing arguments
    if options.TR is not '': tr = float(options.TR)
    else:
        inf = nib.load(dataset).header  # Fix that function!
        tr  = float(round(inf.get_slice_duration() * inf.get_n_slices(),3))

    if 'v' in str(options.basetime):
        basebrik   = int(options.basetime.strip('v'))
    elif 's' in str(options.basetime):
        timetoclip = float(options.basetime.strip('s'))
        basebrik   = int(round(timetoclip/tr))

    # Parse normalization, masking arguments
    if options.mni: options.space = 'MNI_caez_N27+tlrc'
    if options.mask_mode  == '' and options.space:
        options.mask_mode = 'template'

    if options.anat and options.space and options.qwarp:
        valid_qwarp_mode = True
    else: valid_qwarp_mode = False

    # Parse alignment arguments
    if options.coreg_mode == 'aea': options.t2salign   = False
    elif 'lp' in options.coreg_mode : options.t2salign = True
    # align_base         = basebrik
    align_interp       = 'cubic'
    align_interp_final = 'wsinc5'

    if options.anat is not '':
        dsname, _setname   = format_inset(options.input_ds,
                                          options.tes.split(','))

        img = nib.load(dsname)
        epi_cm   = find_CM(dsname)
        anat_cm  = find_CM(options.anat)

        deltas   = [abs(epi_cm[0] - anat_cm[0]),
                    abs(epi_cm[1] - anat_cm[1]),
                    abs(epi_cm[2] - anat_cm[2])]

        # cm_dist  = 20 + sum([dd**2. for dd in deltas])**.5
        cm_dif   = max(deltas)
        voxsz = list(img.header.get_zooms())
        maxvoxsz = float(max(voxsz))
        addslabs          = abs(int(cm_dif/maxvoxsz)) + 10
        zeropad_opts      = " -I {0} -S {0} -A {0} -P {0} -L {0} -R {0} ".format(addslabs)
        oblique_anat_read = check_obliquity(options.anat) != 0

    oblique_epi_read = check_obliquity(dsname) != 0
    if oblique_epi_read or oblique_anat_read:
        oblique_mode = True
    else: oblique_mode = False

    if options.fres:
        if options.qwarp: qw_fres = "-dxyz {}".format(options.fres)
        al_fres = "-mast_dxyz {}".format(options.fres)

    else:
        if options.qwarp: qw_fres = "-dxyz ${voxsize}"
        al_fres = "-mast_dxyz ${voxsize}"

    # Parse selected arguments for underspecified and/or conflicting options
    if options.input_ds is'' or options.tes is '':
        raise OSError("Need at least dataset inputs and TEs. Try meica.py -h")

    # Check for already created meica directories
    meicas = glob.glob('meica.*')
    if any(os.path.isdir(m) for i, m in enumerate(meicas)):
        meica_exists   = True
    else: meica_exists = False

    if not options.overwrite and meica_exists:
        raise OSError("*+ A ME-ICA directory already exists! " +
                      "Use '--OVERWRITE' flag to overwrite it.")

    if os.getenv('DYLD_FALLBACK_LIBRARY_PATH') is None:
        raise OSError("*+ AFNI environmental variables not set! Set " +
                      "DYLD_FALLBACK_LIBRARY_PATH to local AFNI "     +
                      "directory")

    # Check for required inputs for 3dQwarp (i.e., non-linear warping)
    if options.qwarp and (options.anat is '' or not options.space):
        raise OSError("*+ Can't specify Qwarp nonlinear normalization " +
                      "without both anatomical and SPACE template!")

    # Check for aligning options
    if options.mask_mode not in ['func','anat','template']:
        raise OSError("*+ Mask mode option "                   +
                      "'{}' is not ".format(options.mask_mode) +
                      "recognized!")

    if options.anat is '' and options.mask_mode is not 'func':
        raise OSError("*+ Can't do anatomical-based functional " +
                      "masking without an anatomical!")

    # Check for anatomical image if invoked on command line
    if not os.path.isfile(options.anat) and options.anat is not '':
        raise OSError("*+ Can't find anatomical " +
                      "dataset {}!".format(options.anat))

    # Prepare script and enter MEICA directory
    script_list.append("# Set up script run environment")
    script_list.append('set -e')
    script_list.append('export OMP_NUM_THREADS={}'.format(options.cpus))
    script_list.append('export MKL_NUM_THREADS={}'.format(options.cpus))
    script_list.append('export AFNI_3dDespike_NEW=YES')

    if not (options.resume and
            options.tedica_only and
            options.select_only and
            options.export_only):
        script_list.append('mkdir -p meica.{}'.format(setname))

    if options.resume:
        script_list = []
        script_list.append('if [ ! -e '                                  +
                           'meica.{}/_meica.orig.sh ]; '.format(setname) +
                           'then mv '                                    +
                           '`ls meica.{}/_meica*sh` '.format(setname)    +
                           'meica.{}/_meica.orig.sh; fi'.format(setname))

    if not options.tedica_only and not options.select_only:
        script_list.append("cp _meica_{0}.sh meica.{0}/".format(setname))
    script_list.append("cd meica.{}".format(setname))

    echo_nums = range(len(options.tes.split(',')))
    ica_datasets = sorted(echo_nums)

    # Parse anatomical processing options, process anatomical
    if options.anat is not '':
        script_list.append("")
        script_list.append("# Deoblique, unifize, skullstrip, and/or  "      +
                           "autobox anatomical, in starting directory (may " +
                           "take a little while)")
        ns_mprage = options.anat
        anat_prefix, anat_ftype = fparse(options.anat)
        path_anat_prefix        = "{}/{}".format(startdir,anat_prefix)
        if oblique_mode:
            script_list.append("if [ ! -e "                             +
                               "{}_do.nii.gz ".format(path_anat_prefix) +
                               "]; then 3dWarp -overwrite -prefix "     +
                               "{}_do.nii.gz ".format(path_anat_prefix) +
                               "-deoblique "                            +
                               "{}/{}; fi".format(startdir,
                                                  options.anat))
            deobliq_anat = "{}_do.nii.gz".format(anat_prefix)
        else:
            deobliq_anat = options.anat
        if not options.no_skullstrip:
            script_list.append("if [ ! -e "                                   +
                               "{}_ns.nii.gz ]; ".format(path_anat_prefix)    +
                               "then 3dUnifize -overwrite -prefix "           +
                               "{}_u.nii.gz ".format(path_anat_prefix)        +
                               "{0}/{1}; ".format(startdir, deobliq_anat)     +
                               "3dSkullStrip -shrink_fac_bot_lim 0.3 "        +
                               "-orig_vol -overwrite -prefix "                +
                               "{}_ns.nii.gz ".format(path_anat_prefix)       +
                               "-input {}_u.nii.gz; ".format(path_anat_prefix)+
                               "3dAutobox -overwrite -prefix "                +
                               "{}_ns.nii.gz ".format(path_anat_prefix)       +
                               "{}_ns.nii.gz; fi".format(path_anat_prefix))
            ns_mprage     = "{}_ns.nii.gz".format(anat_prefix)

    # Copy in functional datasets as NIFTI (if not in NIFTI already) and
    # calculate rigid body alignment
    vrbase, ftype = fparse(options.input_ds)
    script_list.append("")
    script_list.append("# Copy in functional datasets, reset NIFTI tags " +
                       "as needed")
    for echo in range(len(options.tes.split(','))):
        dsname, setname = format_inset(options.input_ds, options.tes, echo)
        script_list.append("3dcalc -a {}/{} -expr 'a' ".format(startdir,
                                                               dsname) +
                           "-prefix ./{}.nii".format(setname))
        if '.nii' in ftype:
            script_list.append("nifti_tool -mod_hdr -mod_field sform_code 1 " +
                               "-mod_field qform_code 1 -infiles "            +
                               "./{}.nii -overwrite".format(setname))

    script_list.append("")
    script_list.append("# Calculate and save motion and obliquity "        +
                       "parameters, despiking first if not disabled, and " +
                       "separately save and mask the base volume")
    # Determine input to volume registration
    vrAinput = "./{}.nii".format(format_inset(options.input_ds,
                                              options.tes, 0)[0])
    # Compute obliquity matrix
    if oblique_mode:
        if options.anat is not '':
            script_list.append("3dWarp -verb -card2oblique "                 +
                               "{}[0] ".format(vrAinput)                     +
                               "-overwrite -newgrid 1.000000 -prefix "       +
                               "./{}_ob.nii.gz ".format(anat_prefix)         +
                               "{}/{} | \grep  ".format(startdir, ns_mprage) +
                               "-A 4 '# mat44 Obliquity Transformation "     +
                               "::'  > {}_obla2e_mat.1D".format(setname))

        else: script_list.append("3dWarp -overwrite "            +
                                 "-prefix {} ".format(vrAinput)  +
                                 "-deoblique {}".format(vrAinput))

    # Despike and axialize
    if not options.no_despike:
        script_list.append("3dDespike -overwrite "  +
                           "-prefix ./{}_vrA.nii.gz {} ".format(setname,
                                                                vrAinput))
        vrAinput = "./{}_vrA.nii.gz".format(setname)
    if not options.no_axialize:
        script_list.append("3daxialize -overwrite " +
                           "-prefix ./{}_vrA.nii.gz {}".format(setname,
                                                               vrAinput))
        vrAinput = "./{}_vrA.nii.gz".format(setname)

    # Set eBbase
    external_eBbase = False
    if options.align_base is not '':
        if options.align_base.isdigit():
            basevol = '{}[{}]'.format(vrAinput,
                                      options.align_base)
        else:
            basevol = options.align_base
            external_eBbase = True
    else:
        basevol = '{}[{}]'.format(vrAinput,
                                  basebrik)
    script_list.append("3dcalc -a {}  -expr 'a' -prefix ".format(basevol) +
                       "eBbase.nii.gz ")
    if external_eBbase:
        if oblique_mode: script_list.append("3dWarp -overwrite -deoblique "  +
                                            "eBbase.nii.gz eBbase.nii.gz")

        if not options.no_axialize: script_list.append("3daxialize "         +
                                                       "-overwrite -prefix " +
                                                       "eBbase.nii.gz "      +
                                                       "eBbase.nii.gz")

    # Compute motion parameters
    script_list.append("3dvolreg -overwrite -tshift -quintic  "  +
                       "-prefix ./{}_vrA.nii.gz ".format(setname) +
                       "-base eBbase.nii.gz "                    +
                       "-dfile ./{}_vrA.1D ".format(setname)      +
                       "-1Dmatrix_save "                         +
                       "./{0}_vrmat.aff12.1D {1}".format(setname,
                                                         vrAinput))
    vrAinput = "./{}_vrA.nii.gz".format(setname)
    script_list.append("1dcat './{}_vrA.1D[1..6]{{{}..$}}' ".format(setname,
                                                                    basebrik) +
                       "> motion.1D ")
    e2dsin, _setname = format_inset(options.input_ds,
                                    options.tes.split(','),
                                    e=0)
    script_list.append("")
    script_list.append("# Preliminary preprocessing of functional datasets: " +
                       "despike, tshift, deoblique, and/or axialize")

    # Do preliminary preproc for this run
    for echo in range(len(options.tes.split(','))):
        # Determine dataset name
        dataset, _setname = format_inset(options.input_ds,
                                         options.tes.split(','),
                                         e=echo)
        dsin = 'e' + str(echo+1)
        if echo == 0:
            e0_dsin = dsin
        script_list.append("")
        script_list.append("# Preliminary preprocessing dataset " +
                           "{} of TE=".format(dataset) +
                           "{}ms ".format(str(options.tes.split(',')[echo])) +
                           "to produce {}_ts+orig".format(dsin))
        # Pre-treat datasets: De-spike, RETROICOR in the future?
        pfix, ftype = fparse(dataset)
        if not options.no_despike:
            ints_name = "./{}_pt.nii.gz".format(pfix)
            script_list.append("3dDespike -overwrite " +
                               "-prefix {} {}{}".format(ints_name,
                                                        pfix,
                                                        ftype))
        else: ints_name = dataset
        # Time shift datasets
        if options.tpattern is not '':
            tpat_opt = ' -tpattern {} '.format(options.tpattern)
        else:
            tpat_opt = ''
        script_list.append("3dTshift -heptic {} ".format(tpat_opt) +
                           "-prefix ./{}_ts+orig {}".format(dsin,
                                                            ints_name))
        # Force +ORIG label on dataset
        script_list.append("3drefit -view orig {}_ts*HEAD".format(dsin))
        if oblique_mode and options.anat is "":
            script_list.append("3dWarp -overwrite -deoblique "       +
                               "-prefix ./{}_ts+orig ".format(dsin)  +
                               "./{}_ts+orig".format(dsin))
        # Axialize functional dataset
        if not options.no_axialize:
            script_list.append("3daxialize  -overwrite "            +
                               "-prefix ./{}_ts+orig".format(dsin) +
                               " ./{}_ts+orig".format(dsin))
        if oblique_mode:
            script_list.append("3drefit -deoblique " +
                               "-TR {} ".format(tr) +
                               "{}_ts+orig".format(dsin))
        else: script_list.append("3drefit -TR {} {}_ts+orig".format(tr,
                                                                    dsin))

        # Compute T2*, S0, and OC volumes from raw data
    script_list.append("")
    script_list.append("# Prepare T2* and S0 volumes for use in " +
                       "functional masking and (optionally) "     +
                       "anatomical-functional coregistration "    +
                       "(takes a little while).")

    # Do preliminary preproc for this run
    stackline = []
    for echo in range(len(options.tes.split(','))):
        # Determine dataset name
        dsin = 'e' + str(echo+1)

        script_list.append("3dAllineate -overwrite -final NN -NN -float "    +
                           "-1Dmatrix_apply {}_vrmat.aff12.1D'".format(pfix) +
                           "{%i..%i}' " % (int(basebrik),
                                           int(basebrik)+20)     +
                           "-base eBbase.nii.gz " +
                           "-input {}_ts+orig'".format(dsin) +
                           "[{:d}..{:d}]' ".format(basebrik,
                                                   basebrik+20) +
                           "-prefix {}_vrA.nii.gz".format(dsin))
        stackline.append("{}_vrA.nii.gz".format(dsin))
    script_list.append("3dZcat -prefix basestack.nii.gz "+
                       "{}".format(' '.join(stackline)))
    script_list.append("{} ".format(sys.executable)            +
                       "{} ".format(os.path.join(meicadir,
                                                 'meica.libs',
                                                 't2smap.py')) +
                       "-d basestack.nii.gz "                  +
                       "-e {}".format(options.tes))
    script_list.append("3dUnifize -prefix ./ocv_uni+orig ocv.nii")
    script_list.append("3dSkullStrip -no_avoid_eyes -prefix ./ocv_ss.nii.gz " +
                       "-overwrite -input ocv_uni+orig")
    script_list.append("3dcalc -overwrite -a t2svm.nii -b ocv_ss.nii.gz "     +
                       "-expr 'a*ispositive(a)*step(b)' -prefix "             +
                       "t2svm_ss.nii.gz")
    script_list.append("3dcalc -overwrite -a s0v.nii -b ocv_ss.nii.gz "       +
                       "-expr 'a*ispositive(a)*step(b)' -prefix s0v_ss.nii.gz")
    if not options.no_axialize:
        script_list.append("3daxialize -overwrite -prefix " +
                           "t2svm_ss.nii.gz t2svm_ss.nii.gz")
        script_list.append("3daxialize -overwrite -prefix " +
                           "ocv_ss.nii.gz ocv_ss.nii.gz")
        script_list.append("3daxialize -overwrite -prefix " +
                           "s0v_ss.nii.gz s0v_ss.nii.gz")

    # Resume from here on
    if options.resume:
        script_list = []
        script_list.append("export AFNI_DECONFLICT=OVERWRITE")

    # Calculate affine anatomical warp if anatomical provided, then combine
    # motion correction and coregistration parameters
    if options.anat is not '':
        # Copy in anatomical and make sure its in +ORIG space
        script_list.append("")
        script_list.append("# Copy anatomical into ME-ICA directory and " +
                           "process warps")
        script_list.append("cp {}/{}* .".format(startdir, ns_mprage))
        pfix_ns_mprage, ftype_ns_mprage = fparse(ns_mprage)
        if options.space:
            script_list.append("afnibin_loc=`which 3dSkullStrip`")

            if '/' in options.space:
                template_loc, template = os.path.split(options.space)
                script_list.append("templateloc={}".format(template_loc))
            else:
                script_list.append("templateloc=${afnibin_loc%/*}")
            at_ns_mprage = "{}_at.nii.gz".format(pfix_ns_mprage)

            if 'nii' not in ftype_ns_mprage:
                script_list.append("3dcalc -float -a {} ".format(ns_mprage) +
                                   "-expr 'a' "                             +
                                   "-prefix {}.nii.gz".format(pfix_ns_mprage))
            script_list.append("")
            script_list.append("# If can't find affine-warped anatomical, "   +
                               "copy native anatomical here, compute warps "  +
                               "(takes a while) and save in start dir. ;  "   +
                               "otherwise linkin existing files")

            script_list.append("if [ ! -e {}/{} ]; ".format(startdir,
                                                            at_ns_mprage) +
                               "then \@auto_tlrc -no_ss "                 +
                               "-init_xform AUTO_CENTER -base "           +
                               "${{templateloc}}/{} ".format(options.space) +
                               "-input {}.nii.gz ".format(pfix_ns_mprage) +
                               "-suffix _at")

            script_list.append("cp {}.nii {}".format(pfix_ns_mprage + '_at',
                                                     startdir))
            script_list.append("gzip -f {}/{}.nii".format(startdir,
                                                          pfix_ns_mprage +
                                                          '_at'))
            script_list.append("else if [ ! -e {}/{} ]; ".format(startdir,
                                                                 at_ns_mprage)+
                               "then ln "                                     +
                               "-s {}/{} .; fi".format(startdir,
                                                       at_ns_mprage))
            refanat = '{}/{}'.format(startdir,at_ns_mprage)
            script_list.append("fi")

            script_list.append("3dcopy "                                      +
                               "{0}/{1}.nii.gz".format(startdir,
                                                       pfix_ns_mprage +
                                                       '_at')+
                               " {}".format(pfix_ns_mprage +
                                            '_at'))

            script_list.append("rm -f {}+orig.*; ".format(pfix_ns_mprage +
                                                          '_at') +
                               "3drefit -view " +
                               "orig {}+tlrc ".format(pfix_ns_mprage +
                                                      '_at'))

            script_list.append("3dAutobox -overwrite -prefix " +
                               "./abtemplate.nii.gz "          +
                               "${{templateloc}}/{}".format(options.space))
            abmprage = 'abtemplate.nii.gz'
            if options.qwarp:
                script_list.append("")
                script_list.append("# If can't find non-linearly warped " +
                                   "anatomical, compute, save back; "     +
                                   "otherwise link")
                atnl_ns_mprage="{}_atnl.nii.gz".format(pfix_ns_mprage)
                script_list.append("if " +
                                   "[ ! -e {}/{} ]; ".format(startdir,
                                                             atnl_ns_mprage) +
                                   "then ")

                script_list.append("")
                script_list.append("# Compute non-linear warp to standard "   +
                                   "space using 3dQwarp (get lunch, takes a " +
                                   "while) ")
                script_list.append("3dUnifize -overwrite -GM -prefix " +
                                   "./{}u.nii.gz ".format(pfix_ns_mprage +
                                                          '_at') +
                                   "{}/{}".format(startdir,
                                                  at_ns_mprage))
                script_list.append("3dQwarp -iwarp -overwrite -resample "             +
                                   "-useweight -blur 2 2 -duplo -workhard "           +
                                   "-base ${{templateloc}}/{} ".format(options.space) +
                                   "-prefix "                                         +
                                   "{}/{}.nii.gz ".format(startdir,
                                                          pfix_ns_mprage              +
                                                          '_atnl')                    +
                                   "-source "                                         +
                                   "./{}u.nii.gz".format(pfix_ns_mprage               +
                                                         '_at'))
                script_list.append("fi")
                script_list.append("if " +
                                   "[ ! -e {}/{} ]; ".format(startdir,
                                                             atnl_ns_mprage) +
                                   "then " +
                                   "ln -s {}/{} .; fi".format(startdir,
                                                              atnl_ns_mprage))
                # refanat = '{}/{}.nii.gz'.format(startdir,
                #                                 pfix_ns_mprage + '_atnl')

        # Set anatomical reference for anatomical-functional co-registration
        if oblique_mode: alns_mprage = "./{}_ob.nii.gz".format(anat_prefix)
        else: alns_mprage = "{}/{}".format(startdir,ns_mprage)
        if options.coreg_mode=='lp-t2s':
            ama_alns_mprage = alns_mprage
            if not options.no_axialize:
                ama_alns_mprage = os.path.basename(alns_mprage)
                script_list.append("3daxialize -overwrite " +
                                   "-prefix ./{} {}".format(ama_alns_mprage,
                                                            alns_mprage))
            t2salignpath = 'meica.libs/alignp_mepi_anat.py'
            script_list.append("{} ".format(sys.executable) +
                               "{} -t ".format(os.path.join(meicadir,
                                                            t2salignpath)) +
                               "t2svm_ss.nii.gz " +
                               "-a {} ".format(ama_alns_mprage) +
                               "-p mepi {}".format(options.align_args))
            script_list.append("cp alignp.mepi/mepi_al_mat.aff12.1D " +
                               "./{}_al_mat.aff12.1D".format(anat_prefix))

        elif options.coreg_mode=='aea':

            script_list.append("")
            script_list.append("# Using AFNI align_epi_anat.py to drive " +
                               "anatomical-functional coregistration ")
            script_list.append("3dcopy {} ./ANAT_ns+orig ".format(alns_mprage))

            script_list.append("align_epi_anat.py -anat2epi -volreg off "     +
                               "-tshift off -deoblique off -anat_has_skull "  +
                               "no -save_script aea_anat_to_ocv.tcsh -anat "  +
                               "ANAT_ns+orig -epi ocv_uni+orig "              +
                               "-epi_base 0 {}".format(options.align_args))
            script_list.append("cp ANAT_ns_al_mat.aff12.1D " +
                               "{}_al_mat.aff12.1D".format(anat_prefix))
        if options.space:
            tlrc_opt = "{}/{}::WARP_DATA -I".format(startdir,at_ns_mprage)
            inv_tlrc_opt = "{}/{}::WARP_DATA".format(startdir,at_ns_mprage)
            script_list.append("cat_matvec -ONELINE {} > ".format(tlrc_opt) +
                               "{}/{}_xns2at.aff12.1D".format(startdir,
                                                              anat_prefix))
            script_list.append("cat_matvec "                           +
                               "-ONELINE {} > ".format(inv_tlrc_opt)   +
                               "{}_xat2ns.aff12.1D".format(anat_prefix))
        else: tlrc_opt = ""
        if oblique_mode: oblique_opt = "{}_obla2e_mat.1D".format(setname)
        else: oblique_opt = ""

        # pre-Mar 3, 2017, included tlrc affine warp in preprocessing.
        # For new export flexiblity, will do tlrc_opt at export.
        # script_list.append("cat_matvec -ONELINE  %s %s %s_al_mat.aff12.1D " +
        # "-I > %s_wmat.aff12.1D" % (tlrc_opt,oblique_opt,anatprefix,prefix))

        script_list.append("cat_matvec -ONELINE {} ".format(oblique_opt) +
                           "{}_al_mat.aff12.1D ".format(anat_prefix)      +
                           "-I > {}_wmat.aff12.1D".format(setname))
        if options.anat:
            script_list.append("cat_matvec -ONELINE "                       +
                               "{} ".format(oblique_opt)                    +
                               "{}_al_mat.aff12.1D -I ".format(anat_prefix) +
                               "{}_vrmat.aff12.1D  > ".format(setname)      +
                               "{}_vrwmat.aff12.1D".format(setname))

    else: script_list.append("cp {}_vrmat.aff12.1D ".format(setname) +
                             "{}_vrwmat.aff12.1D".format(setname))

    # Preprocess datasets
    script_list.append("")
    script_list.append("# Extended preprocessing of functional datasets")

    # Compute grand mean scaling factor
    script_list.append("3dBrickStat -mask eBbase.nii.gz "          +
                       "-percentile 50 1 50 "                      +
                       "{}_ts+orig[{:d}] ".format(e0_dsin, basebrik) +
                       "> gms.1D")
    script_list.append("gms=`cat gms.1D`; gmsa=($gms); p50=${gmsa[1]}")

    # Set resolution variables
    # Set voxel size for decomp to slightly upsampled version of isotropic appx
    # of native resolution so GRAPPA artifact is not at Nyquist
    script_list.append("voxsize=`ccalc .85*$(3dinfo -voxvol " +
                       "eBbase.nii.gz)**.33`")
    script_list.append("voxdims=\"`3dinfo -adi eBbase.nii.gz` "    +
                       "`3dinfo -adj eBbase.nii.gz` `3dinfo -adk " +
                       "eBbase.nii.gz`\"")
    script_list.append("echo $voxdims > voxdims.1D")
    script_list.append("echo $voxsize > voxsize.1D")

    for echo in range(len(options.tes.split(','))):

        # Determine dataset name
        dataset, _setname = format_inset(options.input_ds,
                                         options.tes.split(','),
                                         e=echo)
        dsin = 'e' + str(echo+1)  # Note using same dsin as in time shifting

        if echo == 0:
            script_list.append("")
            script_list.append("# Preparing functional masking for this " +
                               "ME-EPI run")
            # Update as of Mar 3, 2017, to move to all native analysis
            # abmprage = refanat = ns_mprage
            if options.anat: almaster="-master {}".format(ns_mprage)
            else: almaster = ""
            # print 'almaster line is', almaster  # DEBUG
            # print 'refanat line is', refanat  # DEBUG
            script_list.append("3dZeropad {} ".format(zeropad_opts) +
                               "-prefix eBvrmask.nii.gz ocv_ss.nii.gz[0]")

            if options.anat:
                script_list.append("3dAllineate -overwrite -final NN -NN "  +
                                   "-float -1Dmatrix_apply "                +
                                   "{}_wmat.aff12.1D ".format(setname)      +
                                   "-base {} ".format(ns_mprage)            +
                                   "-input eBvrmask.nii.gz -prefix "        +
                                   "./eBvrmask.nii.gz {} {}".format(almaster,
                                                                    al_fres))
                if options.t2salign or options.mask_mode!='func':
                    script_list.append("3dAllineate -overwrite -final NN "    +
                                       "-NN -float -1Dmatrix_apply "          +
                                       "{}_wmat.aff12.1D ".format(setname)    +
                                       "-base eBvrmask.nii.gz  -input "       +
                                       "t2svm_ss.nii.gz -prefix "             +
                                       "./t2svm_ss_vr.nii.gz "                +
                                       "{} {}".format(almaster, al_fres))
                    script_list.append("3dAllineate -overwrite -final NN "    +
                                       "-NN -float -1Dmatrix_apply "          +
                                       "{}_wmat.aff12.1D ".format(setname)    +
                                       "-base eBvrmask.nii.gz -input "        +
                                       "ocv_uni+orig -prefix "                +
                                       "./ocv_uni_vr.nii.gz "                 +
                                       "{} {}".format(almaster, al_fres))

                    script_list.append("3dAllineate -overwrite -final NN "    +
                                       "-NN -float -1Dmatrix_apply "          +
                                       "{}_wmat.aff12.1D ".format(setname)    +
                                       "-base eBvrmask.nii.gz -input " +
                                       "s0v_ss.nii.gz "+
                                       "-prefix ./s0v_ss_vr.nii.gz "          +
                                       "{} {}".format(almaster, al_fres))
            # Fancy functional masking
            if options.anat and options.mask_mode != 'func':
                if options.space and options.mask_mode == 'template':
                    script_list.append("3dfractionize -overwrite -template "  +
                                       "eBvrmask.nii.gz -input "              +
                                       "abtemplate.nii.gz -prefix "           +
                                       "./anatmask_epi.nii.gz -clip 1")

                    script_list.append("3dAllineate -overwrite -float "      +
                                       "-1Dmatrix_apply %s_xat2ns.aff12.1D " +
                                       "-base eBvrmask.nii.gz -input "       +
                                       "anatmask_epi.nii.gz -prefix "        +
                                       "anatmask_epi.nii.gz "                +
                                       "-overwrite" % (anat_prefix))
                    script_list.append("")
                    script_list.append("# Preparing functional mask using "   +
                                       "information from standard space "     +
                                       "template (takes a little while)")

                if options.mask_mode == 'anat':
                    script_list.append("3dfractionize -template "           +
                                       "eBvrmask.nii.gz -input %s -prefix " +
                                       "./anatmask_epi.nii.gz "             +
                                       "-clip 0.5" % (ns_mprage))
                    script_list.append("")
                    script_list.append("# Preparing functional mask using "  +
                                       "information from anatomical (takes " +
                                       "a little while)")

                script_list.append("3dBrickStat -mask eBvrmask.nii.gz "      +
                                   "-percentile 50 1 50 t2svm_ss_vr.nii.gz " +
                                   "> t2s_med.1D")
                script_list.append("3dBrickStat -mask eBvrmask.nii.gz "    +
                                   "-percentile 50 1 50 s0v_ss_vr.nii.gz " +
                                   "> s0v_med.1D")

                script_list.append("t2sm=`cat t2s_med.1D`; t2sma=($t2sm); " +
                                   "t2sm=${t2sma[1]}")
                script_list.append("s0vm=`cat s0v_med.1D`; s0vma=($s0vm); " +
                                   "s0vm=${s0vma[1]}")

                script_list.append("3dcalc -a ocv_uni_vr.nii.gz -b "          +
                                   "anatmask_epi.nii.gz -c "                  +
                                   "t2svm_ss_vr.nii.gz "                      +
                                   "-d s0v_ss_vr.nii.gz -expr "               +
                                   "\"a-a*equals(equals(b,0)+isnegative(c-${t2sm})" +
                                   "+ispositive(d-${s0vm}),3)\" -overwrite "  +
                                   "-prefix ocv_uni_vr.nii.gz ")

                script_list.append("3dSkullStrip -no_avoid_eyes -overwrite  " +
                                   "-input ocv_uni_vr.nii.gz -prefix "        +
                                   "eBvrmask.nii.gz ")

                if options.fres:
                    resstring = "-dxyz {0} {0} {0}".format(options.fres)
                else: resstring = "-dxyz ${voxsize} ${voxsize} ${voxsize}"

                script_list.append("3dresample -overwrite "           +
                                   "-master {} {} ".format(ns_mprage,
                                                           resstring) +
                                   "-input eBvrmask.nii.gz -prefix "  +
                                   "eBvrmask.nii.gz")

            script_list.append("")
            script_list.append("# Trim empty space off of mask dataset " +
                               "and/or resample")
            script_list.append("3dAutobox -overwrite -prefix " +
                               "eBvrmask.nii.gz eBvrmask.nii.gz")

            # want this isotropic so spatial ops in select_model not confounded
            resstring = "-dxyz ${voxsize} ${voxsize} ${voxsize}"
            script_list.append("3dresample -overwrite -master "             +
                               "eBvrmask.nii.gz {} ".format(resstring)      +
                               "-input eBvrmask.nii.gz "                    +
                               "-prefix eBvrmask.nii.gz")

            script_list.append("3dcalc -float -a eBvrmask.nii.gz -expr " +
                               "'notzero(a)' -overwrite -prefix "        +
                               "eBvrmask.nii.gz")

        # script_list.append("Extended preprocessing dataset %s of TE=%sms" +
        #              " to produce %s_in.nii.gz" % (indata,
        #                                            str(tes.split(',')[echo]),
        #                                            dsin))
        script_list.append("")
        script_list.append("# Apply combined co-registration/motion " +
                           "correction parameter set to " +
                           "{}_ts+orig".format(dsin))
        script_list.append("3dAllineate " +
                           "-final {} ".format(align_interp_final) +
                           "-{} -float ".format(align_interp) +
                           "-1Dmatrix_apply " +
                           "{}_vrwmat.aff12.1D -base ".format(setname) +
                           "eBvrmask.nii.gz -input {}_ts+orig ".format(dsin) +
                           "-prefix ./{}_vr.nii.gz".format(dsin))

        if echo == 0:
            script_list.append("3dTstat -min -prefix "            +
                               "./{}_vr_min.nii.gz ".format(dsin) +
                               "./{}_vr.nii.gz".format(dsin))

            script_list.append("3dcalc -a eBvrmask.nii.gz -b "  +
                               "{}_vr_min.nii.gz ".format(dsin) +
                               "-expr 'step(a)*step(b)' "       +
                               "-overwrite -prefix "            +
                               "eBvrmask.nii.gz")

        if options.FWHM=='0mm':
            script_list.append("3dcalc -float -overwrite -a eBvrmask.nii.gz " +
                               "-b ./{}_vr.nii.gz[{}..$] ".format(dsin,
                                                                  basebrik) +
                               "-expr 'step(a)*b' "  +
                               "-prefix ./{}_sm.nii.gz ".format(dsin))
        else:
            script_list.append("3dBlurInMask -fwhm {} ".format(options.FWHM)  +
                               "-mask eBvrmask.nii.gz "                       +
                               "-prefix ./{}_sm.nii.gz ".format(dsin)         +
                               "./{}_vr.nii.gz[{}..$]".format(dsin,
                                                              basebrik))

        script_list.append("3dcalc -float -overwrite -a "       +
                           "./{}_sm.nii.gz ".format(dsin)       +
                           "-expr \"a*10000/${p50}\" "          +
                           "-prefix ./{}_sm.nii.gz".format(dsin))

        script_list.append("3dTstat -prefix "               +
                           "./{}_mean.nii.gz ".format(dsin) +
                           "./{}_sm.nii.gz".format(dsin))
        if options.detrend:
            script_list.append("3dDetrend -polort %s -overwrite " +
                               "-prefix ./%s_sm.nii.gz "          +
                               "./%s_sm.nii.gz " % (options.detrend,
                                                    dsin,dsin))

        if options.highpass:
            script_list.append("3dBandpass -prefix "               +
                               "./{}_in.nii.gz ".format(dsin)      +
                               "{:f} 99 ".format(options.highpass) +
                               "./{}_sm.nii.gz ".format(dsin))
        else:
            script_list.append("mv {0}_sm.nii.gz {0}_in.nii.gz".format(dsin))

        script_list.append("3dcalc -float -overwrite "          +
                           "-a ./{}_in.nii.gz ".format(dsin)    +
                           "-b ./{}_mean.nii.gz ".format(dsin)  +
                           "-expr 'a+b' "                       +
                           "-prefix ./{}_in.nii.gz".format(dsin))

        script_list.append("3dTstat -stdev " +
                           "-prefix ./{}_std.nii.gz ".format(dsin) +
                           "./{}_in.nii.gz".format(dsin))

        if options.test_proc: script_list.append("exit")

        if not (options.test_proc or options.keep_int):
            script_list.append("rm -f {}_pt.nii.gz ".format(dsin) +
                               "{}_vr.nii.gz ".format(dsin)       +
                               "{}_sm.nii.gz".format(dsin))

    # Spatial concatenation of datasets--
    # this will be removed in future versions based on the argparse feature.
    ica_input  = "zcat_ffd.nii.gz"
    ica_mask   = "zcat_mask.nii.gz"
    zcatstring = ""
    for echo in ica_datasets:
        dsin = 'e' + str(echo+1)
        zcatstring = "{} ./{}_in.nii.gz".format(zcatstring,dsin)
    script_list.append("3dZcat -overwrite -prefix {} {}".format(ica_input,
                                                                zcatstring))
    script_list.append("3dcalc -float -overwrite -a {}[0]".format(ica_input) +
                       " -expr 'notzero(a)' "                                +
                       "-prefix {}".format(ica_mask))

    if options.resume: script_list.append('rm -f TED/pcastate.pklbz')
    if options.tedica_only: script_list = []

    strict_setting = ''
    if options.strict: strict_setting = '--strict'

    if os.path.exists('{}/meica.libs'.format(meicadir)):
        tedanapath = 'meica.libs/tedana.py'
    else: tedanapath = 'tedana.py'

    if not options.preproc_only:
        script_list.append("")
        script_list.append("# Perform TE-dependence analysis " +
                           "(takes a good while)")
        script_list.append("{} {} ".format(sys.executable,
                                           os.path.join(meicadir,
                                                        tedanapath))   +
                           "-e {} ".format(options.tes)                +
                           "-d {} ".format(ica_input)                  +
                           "--sourceTEs={} ".format(options.sourceTEs) +
                           "--kdaw={} ".format(options.daw)            +
                           "--rdaw=1  "                                +
                           "--initcost={} ".format(options.initcost)   +
                           "--finalcost={} ".format(options.finalcost) +
                           "--conv=2.5e-5 {} {}".format(strict_setting,
                                                        options.ted_args))
    if output_prefix == '': output_prefix = setname

    if options.select_only:
        script_list = []
        script_list.append("{} {} ".format(sys.executable,
                                           os.path.join(meicadir,
                                                        tedanapath))          +
                           "-e {}  -d {} ".format(options.tes,
                                                  ica_input)                  +
                           "--sourceTEs={} ".format(options.sourceTEs)        +
                           "--kdaw={} ".format(options.daw)                   +
                           "--rdaw=1 --initcost={} ".format(options.initcost) +
                           "--finalcost={} ".format(options.finalcost)        +
                           "--conv=2.5e-5 --mix=meica_mix.1D "                +
                           "{} {} ".format(strict_setting,
                                           options.ted_args))

    mask_dict = {}  # Need this here

    script_list.append("voxdims=\"`3dinfo -adi eBbase.nii.gz` " +
                       "`3dinfo -adj eBbase.nii.gz` "           +
                       "`3dinfo -adk eBbase.nii.gz`\"")
    script_list.append("echo $voxdims > voxdims.1D")

    # Make the export mask
    script_list.append("3dcalc -float -a TED/ts_OC.nii[0] -overwrite -expr " +
                       "'notzero(a)' -prefix ./export_mask.nii.gz")
    script_list.append("")
    script_list.append("# Copying results to start directory")

    # Create lists for exporting variables
    export_fnames = ['TED/ts_OC.nii', 'TED/dn_ts_OC.nii',
                     'TED/dn_ts_OC_T1c.nii', 'TED/hik_ts_OC_T1c.nii',
                     'TED/betas_hik_OC.nii', 'TED/betas_OC.nii',
                     'TED/feats_OC2.nii']

    export_vars = ['{}_tsoc', '{}_medn', '{}_T1c_medn', '{}_hikts',
                   '{}_mefc','{}_mefl','{}_mefcz']

    export_descr = ['T2* weighted average of ME time series', 'Denoised ' +
                    'timeseries (including thermal noise)', 'Denoised ' +
                    'timeseries with T1 equilibration correction ' +
                    '(including thermal noise)', 'Denoised timeseries with ' +
                    'T1 equilibration correction (no thermal noise)',
                    'Denoised ICA coeff. set for ME-ICR seed-based FC ' +
                    'analysis', 'Full ICA coeff. set for component assessment',
                    'Z-normalized spatial component maps']

    for i, v in enumerate(export_vars):
        export_vars[i] = v.format(output_prefix)

    for_export = list(zip(export_fnames, export_vars, export_descr))

    if not options.preproc_only:

        for i, exp in enumerate(for_export):

            native_export = options.native
            # Set output resolution parameters, either specified fres
            # or original voxel dimensions
            if options.fres:
                resstring = "-dxyz {0} {0} {0}".format(options.fres)
            else: resstring = "-dxyz ${voxdims}"
            to_export = []
            if options.space : export_master ="-master {}".format(abmprage)

            # If Qwarp, do Nwarpapply
            if valid_qwarp_mode:
                warp_code = 'nlw'
                nwarpstring = "-nwarp {0}/{1}_xns2at.aff12.1D '{0}/{2}_WARP.nii.gz'".format(startdir,
                                                                                             anat_prefix,
                                                                                             pfix_ns_mprage + '_atnl')
                script_list.append("3dNwarpApply " +
                                   "-overwrite {} {} ".format(nwarpstring,
                                                              export_master) +
                                   "{} ".format(qw_fres)                     +
                                   "-source {} ".format(exp[0])              +
                                   "-interp wsinc5 "                         +
                                   "-prefix {}_nlw.nii ".format(exp[1]))

                if warp_code not in mask_dict.keys():
                    script_list.append("3dNwarpApply "                       +
                                       "-overwrite {} ".format(nwarpstring)  +
                                       "{} {} ".format(export_master,
                                                       qw_fres)              +
                                       "-source export_mask.nii.gz -interp " +
                                       "wsinc5 -prefix "                     +
                                       "{}_export_mask.nii ".format(warp_code))

                    script_list.append("nifti_tool -mod_hdr -mod_field "      +
                                       "sform_code 2 -mod_field qform_code "  +
                                       "2 -infiles "                          +
                                       "{}_export_mask.nii ".format(warp_code)+
                                       "-overwrite")
                    mask_dict[warp_code] = '{}_export_mask.nii'.format(warp_code)

                to_export.append(('{}_{}'.format(exp[1],warp_code),
                                  '{}_export_mask.nii'.format(warp_code)))

            # If there's a template space, allineate result to that space
            elif options.space:
                warp_code = 'afw'
                script_list.append("3dAllineate -overwrite -final wsinc5 "      +
                                   "-{} -float ".format(align_interp)           +
                                   "-1Dmatrix_apply "                           +
                                   "{}/{}_xns2at.aff12.1D ".format(startdir,
                                                                   anat_prefix) +
                                   "-input {} -prefix ".format(exp[0])          +
                                   "./{}_afw.nii {} {}".format(exp[1],
                                                               export_master,
                                                               al_fres))
                if warp_code not in mask_dict.keys():
                    script_list.append("3dAllineate -overwrite -final "             +
                                       "wsinc5 -{} ".format(align_interp)           +
                                       "-float -1Dmatrix_apply  "                   +
                                       "{}/{}_xns2at.aff12.1D ".format(startdir,
                                                                       anat_prefix) +
                                       "-input export_mask.nii.gz -prefix "         +
                                       "./{}_export_mask.nii ".format(warp_code)    +
                                       "{} {}".format(export_master,
                                                      al_fres))
                    script_list.append("nifti_tool -mod_hdr -mod_field "      +
                                       "sform_code 2 -mod_field qform_code 2 "+
                                       "-infiles "                            +
                                       "{}_export_mask.nii ".format(warp_code)+
                                       "-overwrite")
                    mask_dict[warp_code] = '{}_export_mask.nii'.format(warp_code)

                to_export.append(('{}_{}'.format(exp[1],warp_code),
                                  '{}_export_mask.nii'.format(warp_code)))

            # Otherwise resample
            else: native_export = True
            if native_export:
                if options.anat:
                    native_suffix = 'nat'
                    export_master = "-master {}".format(ns_mprage)
                else:
                    native_suffix = 'epi'
                    export_master = ''
                script_list.append("3dresample -rmode Li -overwrite "       +
                                   "{} {} ".format(export_master,resstring) +
                                   "-input {} -prefix ".format(exp[0])      +
                                   "{}_{}.nii".format(exp[1],
                                                      native_suffix))
                warp_code = native_suffix

                if warp_code not in mask_dict.keys():
                    script_list.append("3dresample -rmode Li -overwrite "   +
                                       "{} {} ".format(export_master,
                                                       resstring)           +
                                       "-input export_mask.nii.gz -prefix " +
                                       "{}_export_mask.nii".format(warp_code))
                    mask_dict[warp_code] = '{}_export_mask.nii'.format(warp_code)
                to_export.append(('{}_{}'.format(exp[1],warp_code),
                                  '{}_export_mask.nii'.format(warp_code)))

            for P, P_mask in to_export:
                script_list.append("3dNotes -h \'{}\' {}.nii".format(exp[2],P))
                if options.anat != '' and '_nat' not in P and options.space is not False:
                    script_list.append("nifti_tool -mod_hdr -mod_field "      +
                                       "sform_code 2 -mod_field qform_code 2 "+
                                       "-infiles {}.nii -overwrite".format(P))

                script_list.append("3dcalc -overwrite -a {} ".format(P_mask)  +
                                   "-b {}.nii ".format(P)                     +
                                   "-expr 'ispositive(a-.5)*b' -prefix "      +
                                   "{0}.nii ; gzip -f {0}.nii; ".format(P)    +
                                   "mv {}.nii.gz {}".format(P,
                                                            startdir))

        script_list.append('cp TED/comp_table.txt ' +
                           '{}/{}_ctab.txt'.format(startdir, output_prefix))
        script_list.append('cp TED/meica_mix.1D ' +
                           '{}/{}_mmix.1D'.format(startdir, output_prefix))

    return script_list


if __name__ == '__main__':
    options = get_options()
    script_list = gen_script(options)

    _dsname, setname = format_inset(options.input_ds,
                                    options.tes.split(','))
    if options.label != '': setname = setname + options.label

    with open("_meica_{}.sh".format(setname), 'w') as file:
        file.write("\n".join(script_list))
