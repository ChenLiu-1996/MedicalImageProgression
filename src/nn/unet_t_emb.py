from .base import BaseNetwork
from .nn_utils import ConvBlock, ResConvBlock, timestep_embedding
from .common_encoder import Encoder
import torch


class T_UNet(BaseNetwork):

    def __init__(self,
                 device: torch.device = torch.device('cpu'),
                 num_filters: int = 16,
                 depth: int = 5,
                 use_residual: bool = False,
                 in_channels: int = 3,
                 out_channels: int = 3,
                 non_linearity: str = 'relu'):
        '''
        An UNet model with time embedding.

        Parameters
        ----------
        device: torch.device
        num_filters : int
            Number of convolutional filters.
        depth: int
            Depth of the model (encoding or decoding)
        use_residual: bool
            Whether to use residual connection within the same conv block
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

        if self.use_residual:
            conv_block = ResConvBlock
            upconv_block = ResConvBlock
        else:
            conv_block = ConvBlock
            upconv_block = ConvBlock

        # This is for the encoder.
        self.encoder = Encoder(in_channels=in_channels,
                               n_f=n_f,
                               depth=self.depth,
                               conv_block=conv_block,
                               non_linearity=self.non_linearity)

        # This is for the decoder.
        self.t_emb_list = torch.nn.ModuleList([])
        self.up_list = torch.nn.ModuleList([])
        self.up_conn_list = torch.nn.ModuleList([])
        for d in range(self.depth):
            self.t_emb_list.append(self._construct_t_emb(n_f * 2 ** d))
            self.up_conn_list.append(torch.nn.Conv2d(n_f * 3 * 2 ** d, n_f * 2 ** d, 1, 1))
            self.up_list.append(upconv_block(n_f * 2 ** d))
        self.t_emb_list = self.t_emb_list[::-1]
        self.up_list = self.up_list[::-1]
        self.up_conn_list = self.up_conn_list[::-1]

        self.t_emb_bottleneck = self._construct_t_emb(n_f * 2 ** self.depth)
        self.out_layer = torch.nn.Conv2d(n_f, out_channels, 1)

    def _construct_t_emb(self, time_embed_dim: int):
        '''
        Construct a block for time embedding.
        '''
        return torch.nn.Sequential(
            torch.torch.nn.Linear(time_embed_dim, time_embed_dim),
            torch.nn.SiLU(),
            torch.torch.nn.Linear(time_embed_dim, time_embed_dim),
        )

    def time_independent_parameters(self):
        '''
        Parameters related to time embedding.
        '''
        return set(self.parameters()) - set(self.t_emb_list.parameters()) - set(self.t_emb_bottleneck.parameters())

    def freeze_time_independent(self):
        '''
        Freeze paramters that are time-independent.
        '''
        for p in self.time_independent_parameters():
            p.requires_grad = False

    def forward(self, x: torch.Tensor, t: torch.Tensor):
        '''
        Time embedding through sinusoidal embedding.
        '''

        assert x.shape[0] == 1

        x, residual_list = self.encoder(x)

        # Time embedding through feature space addition.
        assert x.shape[0] == 1
        t_emb = self.t_emb_bottleneck(timestep_embedding(t, dim=x.shape[1]))
        t_emb = t_emb[:, :, None, None].repeat((1, 1, x.shape[2], x.shape[3]))
        x = x + t_emb

        for d in range(self.depth):
            x = torch.nn.functional.interpolate(x,
                                                scale_factor=2,
                                                mode='bilinear',
                                                align_corners=True)
            res = residual_list.pop(-1)
            t_emb = self.t_emb_list[d](timestep_embedding(t, dim=res.shape[1]))
            t_emb = t_emb[:, :, None, None].repeat((1, 1, res.shape[2], res.shape[3]))
            res = res + t_emb
            x = torch.cat([x, res], dim=1)
            x = self.non_linearity(self.up_conn_list[d](x))
            x = self.up_list[d](x)

        output = self.out_layer(x)

        return output

