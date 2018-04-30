from torch.utils.data import Dataset
from torchvision.datasets import ImageFolder
from torchvision.transforms import Compose

from Preprocessor.Transforms import FromPIL, ToPIL, Resize, ResizeTuple, RandomWarp, RandomTransform, ToTensor


class ImageDatesetCombined(Dataset):
    def __init__(self, dataset_a, dataset_b, size_multiplicator=10):
        """
        :param root_dir:
        :param size_multiplicator:
        """
        self.size_multiplicator = size_multiplicator
        self.transform = Compose([
            FromPIL(),
            Resize(),
            RandomTransform(),
            RandomWarp(),
            ResizeTuple((64, 64)),
            ToPIL(),
            ToTensor()
        ])
        self.dataset_a = ImageFolder(dataset_a, transform=self.transform)
        self.dataset_b = ImageFolder(dataset_b, transform=self.transform)

    def __len__(self):
        return min(len(self.dataset_a), len(self.dataset_b)) * self.size_multiplicator

    def __getitem__(self, i):
        i %= self.size_multiplicator
        return self.dataset_a[i][0], self.dataset_b[i][0]
