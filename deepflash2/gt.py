# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/09_gt.ipynb (unless otherwise specified).

__all__ = ['install', 'import_sitk', 'staple', 'm_voting', 'msk_show', 'GTEstimator']

# Cell
import sys, subprocess, imageio, pandas as pd, numpy as np
from pathlib import Path
from fastcore.basics import GetAttr
from fastprogress.fastprogress import ConsoleProgressBar
from fastai.data.transforms import get_image_files
import matplotlib.pyplot as plt

from .data import _read_msk
from .learner import Config
from .utils import save_mask, iou

# Cell
#from https://stackoverflow.com/questions/12332975/installing-python-module-within-code
def install(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

# Cell
def import_sitk():
    try:
        import SimpleITK
        assert SimpleITK.Version_MajorVersion()==2
    except:
        print('Installing SimpleITK. Please wait.')
        install("SimpleITK==2.0.2")
    import SimpleITK
    return SimpleITK

# Cell
def staple(segmentations, foregroundValue = 1, threshold = 0.5):
    'STAPLE: Simultaneous Truth and Performance Level Estimation with simple ITK'
    sitk = import_sitk()
    segmentations = [sitk.GetImageFromArray(x) for x in segmentations]
    STAPLE_probabilities = sitk.STAPLE(segmentations)
    STAPLE = STAPLE_probabilities > threshold
    #STAPLE = sitk.GetArrayViewFromImage(STAPLE)
    return sitk.GetArrayFromImage(STAPLE)

# Cell
def m_voting(segmentations, labelForUndecidedPixels = 0):
    'Majority Voting from  simple ITK Label Voting'
    sitk = import_sitk()
    segmentations = [sitk.GetImageFromArray(x) for x in segmentations]
    mv_segmentation = sitk.LabelVoting(segmentations, labelForUndecidedPixels)
    return sitk.GetArrayFromImage(mv_segmentation)

# Cell
def msk_show(ax, msk, title):
    ax.imshow(msk)
    ax.set_axis_off()
    ax.set_title(title)

# Cell
class GTEstimator(GetAttr):
    "Class for ground truth estimation"
    _default = 'config'

    def __init__(self, exp_dir='expert_segmentations', config=None, path=None, verbose=1):
        self.exp_dir = exp_dir
        self.config = config or Config()
        self.path = Path(path) if path is not None else Path('.')
        self.mask_fn = lambda exp,msk: self.path/self.exp_dir/exp/msk

        f_list = get_image_files(self.path/self.exp_dir)
        assert len(f_list)>0, f'Found {len(f_list)} masks in "{self.path/self.exp_dir}". Please check your masks and expert folders.'
        ass_str = f'Found unexpected folder structure in {self.path/self.exp_dir}. Please check your provided masks and folders.'
        assert len(f_list[0].relative_to(self.path/self.exp_dir).parents)==2, ass_str

        self.masks = {}
        self.experts = []
        for m in sorted(f_list):
            exp = m.parent.name
            if m.name in self.masks:
                self.masks[m.name].append(exp)
            else:
                self.masks[m.name] = [exp]
            self.experts.append(exp)
        self.experts = sorted(set(self.experts))
        if verbose>0: print(f'Found {len(self.masks)} unique segmentation mask(s) from {len(self.experts)} expert(s)')

    def show_data(self, max_n=6, files=None, figsize=None, **kwargs):
        if files is not None:
            files = [(m,self.masks[m]) for m in files]
        else:
            max_n = min((max_n, len(self.masks)))
            files = list(self.masks.items())[:max_n]
        if not figsize: figsize = (len(self.experts)*3,3)
        for m, exps in files:
            fig, axs = plt.subplots(nrows=1, ncols=len(exps), figsize=figsize, **kwargs)
            for i, exp in enumerate(exps):
                msk = _read_msk(self.mask_fn(exp,m))
                msk_show(axs[i], msk, exp)
            fig.text(0, .5, m, ha='center', va='center', rotation=90)
            plt.tight_layout()
            plt.show()

    def gt_estimation(self, method='STAPLE', show=True, save_dir=None, filetype='.png', figsize = (10,5), **kwargs):
        assert method in ['STAPLE', 'majority_voting']
        res = []
        print(f'Starting ground truth estimation - {method}')
        for m, exps in ConsoleProgressBar(self.masks.items()):
            masks = [_read_msk(self.mask_fn(exp,m)) for exp in exps]
            if method=='STAPLE':
                ref = staple(masks, self.staple_fval, self.staple_thres)
            elif method=='majority_voting':
                ref = m_voting(masks, self.mv_undec)
            #assert ref.mean() > 0, 'Please try again!'
            df_tmp = pd.DataFrame({'method': method, 'file' : m, 'exp' : exps, 'iou': [iou(ref, msk) for msk in masks]})
            res.append(df_tmp)
            if show:
                fig, ax = plt.subplots(ncols=2, figsize=figsize, **kwargs)
                msk_show(ax[0], ref, method)
                av_df = pd.DataFrame([df_tmp[['iou']].mean()], index=['average'], columns=['iou'])
                plt_df = df_tmp.set_index('exp')[['iou']].append(av_df)
                plt_df.columns = [f'Similarity (iou)']
                tbl = pd.plotting.table(ax[1], np.round(plt_df,3), loc='center', colWidths=[.5])
                tbl.set_fontsize(14)
                tbl.scale(1, 2)
                ax[1].set_axis_off()
                fig.text(0, .5, m, ha='center', va='center', rotation=90)
                plt.tight_layout()
                plt.show()
            if save_dir:
                path = self.path/save_dir
                path.mkdir(exist_ok=True, parents=True)
                save_mask(ref, path/Path(m).stem, filetype)

        self.df_res = pd.concat(res)
        self.df_agg = self.df_res.groupby('exp').agg(average_iou=('iou', 'mean'), std_iou=('iou', 'std'))
        if save_dir:
            self.df_res.to_csv(path.parent/f'{method}_vs_experts.csv', index=False)
            self.df_agg.to_csv(path.parent/f'{method}_vs_experts_agg.csv', index=False)