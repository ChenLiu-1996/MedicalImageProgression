from .base import BaseNetwork
from .nn_utils import ConvBlock, UpConvBlock, ResConvBlock, ResUpConvBlock, ODEfunc, ODEBlock
import torch


class AuxNet(BaseNetwork):

    def __init__(self,
                 device: torch.device = torch.device('cpu'),
                 num_filters: int = 16,
                 depth: int = 5,
                 use_residual: bool = False,
                 in_channels: int = 3,
                 out_channels: int = 3,
                 non_linearity: str = 'relu'):
        '''
        Auxiliary Network that performs discrimination and segmentation.

        Parameters
        ----------
        device: torch.device
        num_filters : int
            Number of convolutional filters.
        in_channels: int
            Number of input image channels.
        out_channels: int
            Number of output image channels.
        non_linearity : string
            One of 'relu' and 'softplus'
        '''
        super().__init__()

        self.device = device
        self.depth = depth
        self.use_residual = use_residual
        self.in_channels = in_channels
        self.non_linearity_str = non_linearity
        if self.non_linearity_str == 'relu':
            self.non_linearity = torch.nn.ReLU(inplace=True)
        elif self.non_linearity_str == 'softplus':
            self.non_linearity = torch.nn.Softplus()

        n_f = num_filters  # shorthand

        self.conv1x1 = torch.nn.Conv2d(in_channels, n_f, 1, 1)

        self.down_list = torch.nn.ModuleList([])
        self.down_conn_list = torch.nn.ModuleList([])
        self.up_list = torch.nn.ModuleList([])
        self.up_conn_list = torch.nn.ModuleList([])

        if self.use_residual:
            conv_block = ResConvBlock
            upconv_block = ResUpConvBlock
        else:
            conv_block = ConvBlock
            upconv_block = UpConvBlock

        for d in range(self.depth):
            self.down_list.append(conv_block(n_f * 2 ** d))
            self.down_conn_list.append(torch.nn.Conv2d(n_f * 2 ** d, n_f * 2 ** (d + 1), 1, 1))
            self.up_conn_list.append(torch.nn.Conv2d(n_f * 2 ** (d + 1), n_f * 2 ** d, 1, 1))
            self.up_list.append(upconv_block(n_f * 2 ** d))

        self.up_list = self.up_list[::-1]
        self.up_conn_list = self.up_conn_list[::-1]

        self.bottleneck = ResConvBlock(n_f * 2 ** self.depth)
        self.ode_bottleneck = ODEBlock(ODEfunc(dim=n_f * 2 ** self.depth))
        self.out_layer = torch.nn.Conv2d(n_f, out_channels, 1)


    def forward(self, x: torch.Tensor):
        '''
        Time embedding through ODE.
        '''

        assert x.shape[0] == 1

        # Skip ODE if no time difference.
        use_ode = t.item() != 0
        if use_ode:
            integration_time = torch.tensor([0, t.item()]).float().to(t.device)

        x = self.non_linearity(self.conv1x1(x))

        for d in range(self.depth):
            x = self.down_list[d](x)
            x = self.non_linearity(self.down_conn_list[d](x))
            x = torch.nn.functional.interpolate(x,
                                          scale_factor=0.5,
                                          mode='bilinear',
                                          align_corners=False)
        x = self.bottleneck(x)

        if use_ode:
            x = self.ode_bottleneck(x, integration_time)

        for d in range(self.depth):
            x = torch.nn.functional.interpolate(x,
                                          scale_factor=2,
                                          mode='bilinear',
                                          align_corners=False)
            x = self.non_linearity(self.up_conn_list[d](x))
            x = self.up_list[d](x)

        output = self.out_layer(x)

        return output
