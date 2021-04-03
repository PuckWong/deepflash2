# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/02a_transforms.ipynb (unless otherwise specified).

__all__ = ['preprocess_mask', 'create_pdf', 'random_center', 'calculate_weights', 'lambda_kernel', 'SeparableConv2D',
           'WeightTransformSingle', 'WeightTransform']

# Cell
import torch, cv2, numpy as np
import torch.nn.functional as F
from fastcore.transform import DisplayedTransform
from fastai.torch_core import TensorImage, TensorMask

# Cell
def preprocess_mask(clabels=None, instlabels=None, ignore=None, remove_overlap=True,
                     n_dims = 2, fbr=.1):
    "Calculates the weights from the given mask (classlabels `clabels` or `instlabels`)."

    assert not (clabels is None and instlabels is None), "Provide either clabels or instlabels"

    # If no classlabels are given treat the problem as binary segmentation
    # ==> Create a new array assigning class 1 (foreground) to each instance
    if clabels is None:
        clabels = (instlabels[:] > 0).astype(int)
    else: clabels = np.array(clabels[:])

    if remove_overlap:
        # Initialize label and weights arrays with background
        labels = np.zeros_like(clabels)
        classes = np.unique(clabels)[1:]
        # If no instance labels are given, generate them now
        if instlabels is None:
            # Creating instance labels from mask
            instlabels = np.zeros_like(clabels)
            nextInstance = 1
            for c in classes:
                #comps2, nInstances2 = ndimage.measurements.label(clabels == c)
                nInstances, comps = cv2.connectedComponents((clabels[:] == c).astype('uint8'), connectivity=4)
                nInstances -=1
                instlabels[comps > 0] = comps[comps > 0] + nextInstance
                nextInstance += nInstances

        for c in classes:
            # Extract all instance labels of class c
            il = (instlabels * (clabels[:] == c)).astype(np.int16)
            instances = np.unique(il)[1:]

            # Generate background ridges between touching instances
            # of that class, avoid overlapping instances
            dil = cv2.morphologyEx(il, cv2.MORPH_CLOSE, kernel=np.ones((3,) * n_dims))
            overlap_cand = np.unique(np.where(dil!=il, dil, 0))
            labels[np.isin(il, overlap_cand, invert=True)] = c

            for instance in overlap_cand[1:]:
                objectMaskDil = cv2.dilate((labels == c).astype('uint8'), kernel=np.ones((3,) * n_dims),iterations = 1)
                labels[(instlabels == instance) & (objectMaskDil == 0)] = c
    else:
        labels = clabels

    return labels#.astype(np.int32)

# Cell
def create_pdf(labels, ignore=None, fbr=.1, scale=448):
    'Creates a cumulated probability density function (PDF) for weighted sampling '

    pdf = (labels[:] > 0) + (labels[:] == 0) * fbr

    # Set weight and sampling probability for ignored regions to 0
    if ignore is not None:
        pdf[ignore[:]] = 0

    if scale:
        if pdf.shape[0]>scale:
            scale_w = int((pdf.shape[1]/pdf.shape[0])*scale)
            pdf = cv2.resize(pdf, dsize=(scale_w, scale), interpolation=cv2.INTER_CUBIC)

    return np.cumsum(pdf/np.sum(pdf))

# Cell
def random_center(pdf, orig_shape, scale=448):
    'Sample random center using PDF'
    scale_y = int((orig_shape[1]/orig_shape[0])*scale)
    cx, cy = np.unravel_index(np.argmax(pdf > np.random.random()), (scale,scale_y))
    cx = int(cx*orig_shape[0]/scale)
    cy = int(cy*orig_shape[1]/scale_y)
    return cx, cy

# Cell
def calculate_weights(clabels=None, instlabels=None, ignore=None,
                      n_dims = 2, bws=10, fds=10, bwf=10, fbr=.1):
    """
    Calculates the weights from the given mask (classlabels `clabels` or `instlabels`).
    """

    assert not (clabels is None and instlabels is None), "Provide either clabels or instlabels"

    # If no classlabels are given treat the problem as binary segmentation
    # ==> Create a new array assigning class 1 (foreground) to each instance
    if clabels is None:
        clabels = (instlabels[:] > 0).astype(int)
    else: clabels = np.array(clabels[:])

    # Initialize label and weights arrays with background
    labels = np.zeros_like(clabels)
    wghts = fbr * np.ones_like(clabels)
    frgrd_dist = np.zeros_like(clabels, dtype='float32')
    classes = np.unique(clabels)[1:]

    #assert len(classes)==clabels.max(), "Provide consecutive classes, e.g. pixel label 1 and 2 for two classes"

    # If no instance labels are given, generate them now
    if instlabels is None:
        # Creating instance labels from mask
        instlabels = np.zeros_like(clabels)
        nextInstance = 1
        for c in classes:
            #comps2, nInstances2 = ndimage.measurements.label(clabels == c)
            nInstances, comps = cv2.connectedComponents((clabels == c).astype('uint8'), connectivity=4)
            nInstances -=1
            instlabels[comps > 0] = comps[comps > 0] + nextInstance
            nextInstance += nInstances

    for c in classes:
        # Extract all instance labels of class c
        il = (instlabels * (clabels == c)).astype(np.int16)
        instances = np.unique(il)[1:]

        # Generate background ridges between touching instances
        # of that class, avoid overlapping instances
        dil = cv2.morphologyEx(il, cv2.MORPH_CLOSE, kernel=np.ones((3,) * n_dims))
        overlap_cand = np.unique(np.where(dil!=il, dil, 0))
        labels[np.isin(il, overlap_cand, invert=True)] = c

        for instance in overlap_cand[1:]:
            objectMaskDil = cv2.dilate((labels == c).astype('uint8'), kernel=np.ones((3,) * n_dims),iterations = 1)
            labels[(instlabels == instance) & (objectMaskDil == 0)] = c

        # Generate weights
        min1dist = 1e10 * np.ones(labels.shape)
        min2dist = 1e10 * np.ones(labels.shape)
        for instance in instances:
            #dt2 = ndimage.morphology.distance_transform_edt(instlabels != instance)
            dt = cv2.distanceTransform((instlabels != instance).astype('uint8'), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
            frgrd_dist += np.exp(-dt ** 2 / (2*fds ** 2))
            min2dist = np.minimum(min2dist, dt)
            newMin1 = np.minimum(min1dist, min2dist)
            newMin2 = np.maximum(min1dist, min2dist)
            min1dist = newMin1
            min2dist = newMin2
        wghts += bwf * np.exp(-(min1dist + min2dist) ** 2 / (2*bws ** 2))

    # Set weight for distance to the closest foreground object
    wghts[labels == 0] += (1-fbr)*frgrd_dist[labels == 0]
    # Set foreground weights to 1
    wghts[labels > 0] = 1
    pdf = (labels > 0) + (labels == 0) * fbr

    # Set weight and sampling probability for ignored regions to 0
    if ignore is not None:
        wghts[ignore] = 0
        pdf[ignore] = 0

    return (labels.astype(np.int32),
            wghts.astype(np.float32),
            pdf.astype(np.float32))

# Cell
def lambda_kernel(ks, lmbda):
    x = torch.arange(ks, dtype=torch.float) - ks // 2
    if ks % 2 == 0: x = x + 0.5
    d = torch.sqrt(x**2)
    return torch.exp(-d/lmbda)

# Cell
class SeparableConv2D(torch.nn.Module):
    'Apply kernel on a 2d Tensor as a sequence of 1-D convolution filters.'
    def __init__(self, lmbda, channels, ks=73, padding_mode='constant'):
        super().__init__()

        self.channels = channels # assuming same 2D dimensions for H/W
        ks = ks if ks % 2 == 1 else ks+1
        self.padding = ((ks-1)//2, (ks-(ks%2))//2)
        self.padding_mode = padding_mode
        kernel = lambda_kernel(ks, lmbda)
        # Reshape to depthwise convolutional weight
        kernel = kernel.view(1, 1, -1)
        kernel = kernel.repeat(channels, 1, 1)
        self.weight = kernel

    def forward(self, inp):
        'Apply 1d gaussian filter to 2d input.'
        # assuming shape [ROIS, H, W]
        weight = self.weight.to(inp)
        for _ in range(2):
            inp = F.conv1d(F.pad(inp, self.padding, mode=self.padding_mode), weight=weight, groups=self.channels)
            inp = torch.transpose(inp, 1,2)
        return inp#.contiguous()

# Cell
class WeightTransformSingle(DisplayedTransform):
    def __init__(self, channels, bws=10, fds=10, bwf=1, fbr=.1, lmbda=0.35, ks=73):
        self.bws, self.fds, self.bwf, self.fbr= bws, fds, bwf, fbr
        self.channels, self.lmbda = channels, lmbda
        self.filter = SeparableConv2D(self.lmbda, channels, ks=ks)
        #print('Using real-time weight calculation.')

    def _distance_transform(self, x):
        'Fast convolutional distance transform'
        x = self.filter(x)
        return -self.lmbda*torch.log(x)

    def encodes(self, x:torch.Tensor):
        #if isinstance(x, TensorImage) or isinstance(x, TensorMask): return x

        labels = (torch.sum(x, dim=0)>0)
        wghts = self.fbr * torch.ones((self.channels,)*2).to(x)
        if x.size(0)==0: return wghts
        dt = self._distance_transform(x)

        # Foreground_dist
        fd = torch.sum(torch.exp(-dt**2/(2*self.fds**2)), dim=0)
        wghts[labels == 0] += (1-self.fbr)*fd[labels == 0]

        # Border Weights
        bw_max = torch.max(dt, dim=0)[0]
        bw_min = torch.min(dt, dim=0)[0]
        wghts += self.bwf * torch.exp(-(bw_max + bw_min)**2/ (2*self.bws ** 2))

        # Set foreground weights to 1
        wghts[labels > 0] = 1.
        return wghts

# Cell
class WeightTransform(WeightTransformSingle):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def encodes(self, b:torch.Tensor):
        if isinstance(b, TensorImage) or isinstance(b, TensorMask): return b
        w_ll = []
        for x in b:
            x = (torch.eye(int(x.max()+1))[x.type(torch.long)][...,1:]).to(x)
            x = x.permute(2,0,1)
            labels = (torch.sum(x, dim=0)>0)
            wghts = self.fbr * torch.ones((self.channels,)*2).to(x)
            if x.size(0)>0:
                dt = self._distance_transform(x)

                # Foreground_dist
                fd = torch.sum(torch.exp(-dt**2/(2*self.fds**2)), dim=0)
                wghts[labels == 0] += (1-self.fbr)*fd[labels == 0]

                # Border Weights
                bw_max = torch.max(dt, dim=0)[0]
                bw_min = torch.min(dt, dim=0)[0]
                wghts += self.bwf * torch.exp(-(bw_max + bw_min)**2/ (2*self.bws ** 2))

                # Set foreground weights to 1
                wghts[labels > 0] = 1.
            w_ll.append(wghts)
        #assert x.device==torch.device(type='cpu')
        return torch.stack(w_ll).to(x)
